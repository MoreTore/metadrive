from collections import deque

import gym
import numpy as np

from pgdrive.envs.pgdrive_env import PGDriveEnv
from pgdrive.obs.observation_base import ObservationBase
from pgdrive.obs.state_obs import LidarStateObservation
from pgdrive.utils import Config, clip, norm


class LidarStateObservationV2(LidarStateObservation):
    def __init__(self, vehicle_config):
        super(LidarStateObservationV2, self).__init__(vehicle_config)
        self._cloud_point_stack = deque(maxlen=vehicle_config["num_stacks"])
        self.obs_mode = self.config["obs_mode"]
        assert self.obs_mode in ["w_navi", "w_ego", "w_both"]

    @property
    def observation_space(self):
        shape = [6 + 4 + self.config["lane_line_detector"]["num_lasers"] + self.config["side_detector"]["num_lasers"]]
        if self.config["lidar"]["num_lasers"] > 0 and self.config["lidar"]["distance"] > 0:
            # Number of lidar rays and distance should be positive!
            shape[0] += self.config["lidar"]["num_lasers"] * self.config["num_stacks"] + \
                        self.config["lidar"]["num_others"] * 4

        if self.obs_mode in ["w_navi", "w_both"]:
            shape[0] += 6

        if self.obs_mode in ["w_ego", "w_both"]:
            shape[0] += 4

        return gym.spaces.Box(-0.0, 1.0, shape=tuple(shape), dtype=np.float32)

    def state_observe(self, vehicle):
        navi_info = vehicle.navigation.get_navi_info()

        if self.config["obs_mode"] in ["w_navi", "w_both"]:
            navi_info = navi_info.tolist()
        else:
            # Only keep the checkpoints information!
            navi_info = [navi_info[0], navi_info[1], navi_info[5], navi_info[6]]

        ego_state = self.vehicle_state(vehicle)
        return np.asarray(ego_state + navi_info, dtype=np.float32)

    def lidar_observe(self, vehicle):
        assert self.config["lidar"]["num_others"] == 0
        cloud_points = super(LidarStateObservationV2, self).lidar_observe(vehicle)
        self._cloud_point_stack.append(cloud_points)
        ret = []
        for ps in self._cloud_point_stack:
            ret += ps
        return ret

    def vehicle_state(self, vehicle):
        """
        Wrap vehicle states to list
        """
        # update out of road
        info = []
        if hasattr(vehicle, "side_detector") and vehicle.side_detector.available:
            info += self._add_noise_to_cloud_points(
                vehicle.side_detector.perceive(vehicle, vehicle.engine.physics_world.static_world).cloud_points,
                gaussian_noise=self.config["side_detector"]["gaussian_noise"],
                dropout_prob=self.config["side_detector"]["dropout_prob"]
            )
        else:
            pass
            # raise ValueError()
        # print("Current side detector min: {}, max: {}, mean: {}".format(min(info), max(info), np.mean(info)))
        # current_reference_lane = vehicle.navigation.current_ref_lanes[-1]

        if self.obs_mode in ["w_ego", "w_both"]:
            lateral_to_left, lateral_to_right, = vehicle.dist_to_left_side, vehicle.dist_to_right_side
            total_width = float(
                (vehicle.navigation.get_current_lane_num() + 1) * vehicle.navigation.get_current_lane_width()
            )
            lateral_to_left /= total_width
            lateral_to_right /= total_width
            info += [clip(lateral_to_left, 0.0, 1.0), clip(lateral_to_right, 0.0, 1.0)]
            current_reference_lane = vehicle.navigation.current_ref_lanes[-1]
            info.append(vehicle.heading_diff(current_reference_lane))

            _, lateral = vehicle.lane.local_coordinates(vehicle.position)
            info.append(clip((lateral * 2 / vehicle.navigation.get_current_lane_width() + 1.0) / 2.0, 0.0, 1.0))

        info += [
            # vehicle.heading_diff(current_reference_lane),
            # Note: speed can be negative denoting free fall. This happen when emergency brake.
            clip((vehicle.speed + 1) / (vehicle.max_speed + 1), 0.0, 1.0),
            clip((vehicle.throttle_brake + 1) / 2, 0.0, 1.0),
            clip((vehicle.steering / vehicle.MAX_STEERING + 1) / 2, 0.0, 1.0),
            clip((vehicle.last_current_action[0][0] + 1) / 2, 0.0, 1.0),
            clip((vehicle.last_current_action[0][1] + 1) / 2, 0.0, 1.0)
        ]
        heading_dir_last = vehicle.last_heading_dir
        heading_dir_now = vehicle.heading
        cos_beta = heading_dir_now.dot(heading_dir_last) / (norm(*heading_dir_now) * norm(*heading_dir_last))
        beta_diff = np.arccos(clip(cos_beta, 0.0, 1.0))
        # print(beta)
        yaw_rate = beta_diff / 0.1
        # print(yaw_rate)
        info.append(clip(yaw_rate, 0.0, 1.0))

        if vehicle.lane_line_detector.available:
            info += self._add_noise_to_cloud_points(
                vehicle.lane_line_detector.perceive(vehicle, vehicle.engine.physics_world.static_world).cloud_points,
                gaussian_noise=self.config["lane_line_detector"]["gaussian_noise"],
                dropout_prob=self.config["lane_line_detector"]["dropout_prob"]
            )
        return info

    def reset(self, env, vehicle=None):
        ret = super(LidarStateObservationV2, self).reset(env, vehicle)
        self._cloud_point_stack.clear()
        for _ in range(self.config["num_stacks"]):
            self._cloud_point_stack.append([1.0] * self.config["lidar"]["num_lasers"])
        return ret


class PGDriveEnvReduced(PGDriveEnv):
    @classmethod
    def default_config(cls) -> Config:
        config = PGDriveEnv.default_config()
        config["vehicle_config"]["lidar"]["num_others"] = 0
        config["vehicle_config"]["lidar"]["num_lasers"] = 240
        config["vehicle_config"]["side_detector"]["num_lasers"] = 120
        config["vehicle_config"]["num_stacks"] = 1
        config["obs_mode"] = None  # ["w_navi", "w_ego", "w_both"]
        return config

    def get_single_observation(self, vehicle_config: "Config") -> "ObservationBase":
        assert not self.config["offscreen_render"]
        vehicle_config["obs_mode"] = self.config["obs_mode"]
        return LidarStateObservationV2(vehicle_config)

    def reward_function(self, vehicle_id: str):
        r, r_info = super(PGDriveEnvReduced, self).reward_function(vehicle_id)
        r_info["out_of_route"] = False
        if self.vehicles[vehicle_id].out_of_route:
            r = -abs(r)
            r_info["out_of_route"] = True
        return r, r_info


if __name__ == '__main__':

    def _act(env, action):
        assert env.action_space.contains(action)
        obs, reward, done, info = env.step(action)
        assert env.observation_space.contains(obs)
        assert np.isscalar(reward)
        assert isinstance(info, dict)

    # env = PGDriveEnvReduced({"vehicle_config": {"num_stacks": 2}})

    for om in ["w_ego", "w_navi", "w_both"]:
        env = PGDriveEnvReduced({"obs_mode": om})
        try:
            obs = env.reset()
            assert env.observation_space.contains(obs)
            for _ in range(10):
                o, r, d, i = env.step(env.action_space.sample())
                env.reset()
            _act(env, env.action_space.sample())
            for x in [-1, 0, 1]:
                obs = env.reset()
                assert env.observation_space.contains(obs)
                for y in [-1, 0, 1]:
                    _act(env, [x, y])
        finally:
            env.close()
            print("Finish om: ", om)