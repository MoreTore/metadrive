import logging

from metadrive.component.lane.waypoint_lane import WayPointLane, LineType
from metadrive.utils.math_utils import norm
from metadrive.constants import WaymoLaneProperty
from metadrive.engine.asset_loader import AssetLoader
from metadrive.utils.waymo_utils.waymo_utils import read_waymo_data, convert_polyline_to_metadrive

from metadrive.utils.waymo_utils.waymo_utils import RoadLineType, RoadEdgeType, convert_polyline_to_metadrive
from metadrive.constants import LineType, LineColor


class WaymoLane(WayPointLane):
    def __init__(self, waymo_lane_id: int, waymo_map_data: dict):
        """
        Extract the lane information of one waymo lane, and do coordinate shifting
        """

        lane_data = waymo_map_data[waymo_lane_id]

        super(WaymoLane, self).__init__(
            center_line_points=convert_polyline_to_metadrive(lane_data[WaymoLaneProperty.POLYLINE]),
            width=self.get_lane_width(waymo_lane_id, waymo_map_data)
        )

        self.index = waymo_lane_id

        self.entry_lanes = lane_data[WaymoLaneProperty.ENTRY]
        self.exit_lanes = lane_data[WaymoLaneProperty.EXIT]
        self.left_lanes = lane_data[WaymoLaneProperty.LEFT_NEIGHBORS]
        self.right_lanes = lane_data[WaymoLaneProperty.RIGHT_NEIGHBORS]

        if len(self.left_lanes) > 0:
            left_type = LineType.BROKEN
        else:
            left_type = LineType.CONTINUOUS

        if len(self.right_lanes) > 0:
            right_type = LineType.BROKEN
        else:
            right_type = LineType.CONTINUOUS


        lane_type = lane_data.get("type", None)
        if RoadLineType.is_road_line(lane_type):
            if len(lane_data[WaymoLaneProperty.POLYLINE]) <= 1:
                pass
            if RoadLineType.is_broken(lane_type):
                self.line_types = (LineType.BROKEN, LineType.BROKEN)
            else:
                self.line_types = (LineType.CONTINUOUS, LineType.CONTINUOUS)
        elif RoadEdgeType.is_road_edge(lane_type) and RoadEdgeType.is_sidewalk(lane_type):
            self.line_types = (LineType.CONTINUOUS, LineType.CONTINUOUS)
            pass
        elif RoadEdgeType.is_road_edge(lane_type) and not RoadEdgeType.is_sidewalk(lane_type):
            self.line_types = (LineType.CONTINUOUS, LineType.CONTINUOUS)
            pass
        elif lane_type == "center_lane" or lane_type is None:
            # self.line_types = (LineType.BROKEN, LineType.BROKEN)
            left_type = left_type or LineType.BROKEN
            right_type = right_type or LineType.BROKEN
            pass
        else:
            raise ValueError("Can not build lane line type: {}".format(type))

        self.line_types = (left_type, right_type)

        self.line_colors = [
            LineColor.YELLOW if left_type == LineType.CONTINUOUS else LineColor.GREY,
            LineColor.YELLOW if right_type == LineType.CONTINUOUS else LineColor.GREY
        ]

    @staticmethod
    def get_lane_width(waymo_lane_id, waymo_map_data):
        """
        We use this function to get possible lane width from raw data
        """
        right_lanes = waymo_map_data[waymo_lane_id][WaymoLaneProperty.RIGHT_NEIGHBORS]
        left_lanes = waymo_map_data[waymo_lane_id][WaymoLaneProperty.LEFT_NEIGHBORS]
        if len(right_lanes) + len(left_lanes) == 0:
            return max(sum(waymo_map_data[waymo_lane_id]["width"][0]), 6)
        dist_to_left_lane = 0
        dist_to_right_lane = 0
        if len(right_lanes) > 0:
            right_lane = waymo_map_data[right_lanes[0]["id"]]
            self_start = right_lanes[0]["indexes"][0]
            neighbor_start = right_lanes[0]["indexes"][2]
            n_point = right_lane[WaymoLaneProperty.POLYLINE][neighbor_start]
            self_point = waymo_map_data[waymo_lane_id][WaymoLaneProperty.POLYLINE][self_start]
            dist_to_right_lane = norm(n_point[0] - self_point[0], n_point[1] - self_point[1])
        if len(left_lanes) > 0:
            left_lane = waymo_map_data[left_lanes[-1]["id"]]
            self_start = left_lanes[-1]["indexes"][0]
            neighbor_start = left_lanes[-1]["indexes"][2]
            n_point = left_lane[WaymoLaneProperty.POLYLINE][neighbor_start]
            self_point = waymo_map_data[waymo_lane_id][WaymoLaneProperty.POLYLINE][self_start]
            dist_to_left_lane = norm(n_point[0] - self_point[0], n_point[1] - self_point[1])
        return max(dist_to_left_lane, dist_to_right_lane, 6)

    def __del__(self):
        logging.debug("WaymoLane is released")


if __name__ == "__main__":
    file_path = AssetLoader.file_path("waymo", "test.pkl", return_raw_style=False)
    read_data = read_waymo_data(file_path)
    print(read_data)
    lane = WaymoLane(108, read_data["map"])
