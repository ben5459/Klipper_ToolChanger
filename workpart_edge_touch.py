# Touch probe workpart edges for milling. Allows to determine the origin and
# rotation of the reference frame in the X-Y plane from the edges of the
# stock workpart. Requires a probe which is sensitive also in X and Y (e.g.
# a load-cell based probe, see load_cell_probe.py).
#
# Copyright (C) 2020  Martin Hierholzer <martin@hierholzer.info>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging, time, math
from mathutil import linear_regression


DIRECTION_CHOICE_LIST={
  'X+':['x',+1],
  'x+':['x',+1],
  'X-':['x',-1],
  'x-':['x',-1],
  'Y+':['y',+1],
  'y+':['y',+1],
  'Y-':['y',-1],
  'y-':['y',-1]
}


class WorkpartEdgeTouch:
    def __init__(self, config):
        self.name = config.get_name()
        self.printer = config.get_printer()

        self.speed = config.getfloat('speed', 5., above=0.)
        self.tool_radius = config.getfloat('tool_radius', above=0.)

        self.gcode = self.printer.lookup_object('gcode')

        self.gcode.register_command('EDGE_TOUCH',
            self.cmd_EDGE_TOUCH,
            desc=self.cmd_EDGE_TOUCH_help)

        self.gcode.register_command('CLEAR_WORKPART',
            self.cmd_CLEAR_WORKPART,
            desc=self.cmd_CLEAR_WORKPART_help)

        self.gcode.register_command('COMPUTE_WORKPART',
            self.cmd_COMPUTE_WORKPART,
            desc=self.cmd_COMPUTE_WORKPART_help)

        self.gcode.register_command('CLEAR_WORKPART_TRANSFORM',
            self.cmd_CLEAR_WORKPART_TRANSFORM,
            desc=self.cmd_CLEAR_WORKPART_TRANSFORM_help)

        self.scans = {}
        self.scans['x'] = eval(config.get('x_scans', "[]"))
        self.scans['y'] = eval(config.get('y_scans', "[]"))

        self.rot_mat = [ [1,0], [0,1] ]
        self.offset = [0,0]

        # Register transform
        gcode_move = self.printer.load_object(config, 'gcode_move')
        self.normal_transform = gcode_move.set_move_transform(self, force=True)


    cmd_EDGE_TOUCH_help = "Add current position (e.g. after running a probe) " \
            + "as edge touch point. This command neither runs the probe nor "  \
            + "recomputes the coordinate transform."


    cmd_COMPUTE_WORKPART_help = "Computes the coordinate transform based on "  \
            + "the previously recorded edge touch positions."


    cmd_CLEAR_WORKPART_help = "Clear all recorded edge touch positions and "   \
            + "reset the coordinate transform."


    cmd_CLEAR_WORKPART_TRANSFORM_help = "Clear only the workpart transform "   \
            + "but leave the recorded points intact."


    def cmd_EDGE_TOUCH(self, gcmd):
        toolhead = self.printer.lookup_object('toolhead')
        configfile = self.printer.lookup_object('configfile')

        dirpara = gcmd.get("DIRECTION")
        if dirpara not in DIRECTION_CHOICE_LIST :
          raise gcmd.error("DIRECTION parameter has illegal value.")
        (axis,direction) = DIRECTION_CHOICE_LIST[dirpara]

        # update dictionary of scans
        toolhead = self.printer.lookup_object('toolhead')
        pos = toolhead.get_position()
        theScan = { 'direction': direction,
                    'pos': pos }
        self.scans[axis].append(theScan)

        # update config file
        configfile.set(self.name, 'x_scans', self.scans['x'])
        configfile.set(self.name, 'y_scans', self.scans['y'])
        gcmd.respond_info("The SAVE_CONFIG command will update the printer\n"
                  "config file and restart the printer.")


    def cmd_CLEAR_WORKPART(self, gcmd):
        configfile = self.printer.lookup_object('configfile')
        self.scans['x'] = []
        self.scans['y'] = []
        self.rot_mat = [ [1,0], [0,1] ]
        self.offset = [0,0]
        configfile.set(self.name, 'x_scans', self.scans['x'])
        configfile.set(self.name, 'y_scans', self.scans['y'])
        gcmd.respond_info("The SAVE_CONFIG command will update the printer\n"
                  "config file and restart the printer.")


    def cmd_CLEAR_WORKPART_TRANSFORM(self, gcmd):
        self.rot_mat = [ [1,0], [0,1] ]
        self.offset = [0,0]


    def cmd_COMPUTE_WORKPART(self, gcmd):

        # consistency check: each axis must have all touch points in the same
        # direction
        x_direction = self.scans['x'][0]['direction']
        y_direction = self.scans['y'][0]['direction']
        for scan in self.scans['x'] :
          if scan['direction'] != x_direction :
            raise gcmd.error("All touch points for the x axis must have the " +
              "same direction!")
        for scan in self.scans['y'] :
          if scan['direction'] != y_direction :
            raise gcmd.error("All touch points for the y axis must have the " +
              "same direction!")

        # Fit new Y axis if possible (points scanned in X direction)
        angle_y = None
        intersect_y = None
        if len(self.scans['x']) > 1 :
          x = []
          y = []
          for scan in self.scans['x'] :
            x.append(scan['pos'][0])
            y.append(scan['pos'][1])
          # Perform fit with x and y swapped, to prevent slope to be close to
          # infinity. Since the swap mirrors the angle, it needs to be mirrored
          # back (switch sign).
          m,b,r,sm,sb = linear_regression(y, x, 0.01)
          gcmd.respond_info("Y axis fit: "+str(m)+"*y + " + str(b))
          gcmd.respond_info("r = "+str(r)+" sm = "+str(sm)+" sb = "+str(sb))
          angle_y = -math.atan(m)
          err_angle_y = abs(-math.atan(m+sm) - angle_y) / angle_y
          gcmd.respond_info("angle_y = "+str(angle_y*180/math.pi))
          intersect_y = b

        # Fit new X axis if possible (points scanned in Y direction)
        angle_x = None
        intersect_x = None
        if len(self.scans['y']) > 1 :
          x = []
          y = []
          for scan in self.scans['y'] :
            x.append(scan['pos'][0])
            y.append(scan['pos'][1])
          m,b,r,sm,sb = linear_regression(x, y, 0.01)
          gcmd.respond_info("X axis fit: "+str(m)+"*x + " + str(b))
          gcmd.respond_info("r = "+str(r)+" sm = "+str(sm)+" sb = "+str(sb))
          angle_x = math.atan(m)
          err_angle_x = abs(-math.atan(m+sm) - angle_x) / angle_x
          gcmd.respond_info("angle_x = "+str(angle_x*180/math.pi))
          intersect_x = b

        # Make sure angle is defined at least through one axis
        if angle_y == None and angle_x == None :
          raise gcmd.error("Too few touch points, cannot determine rotation "
            + "angle!")
        elif angle_y == None :
          angle = angle_x
        elif angle_x == None :
          angle = angle_y
        else :
          # Average angle, weighted with error
          angle = (angle_y/err_angle_y+angle_x/err_angle_x)/                   \
                  (1/err_angle_x+1/err_angle_y)

        gcmd.respond_info("angle = "+str(angle*180/math.pi))

        # Determine X axis intersection with machine Y axis based on new angle
        intersect_x = 0
        for scan in self.scans['y'] :
          b = scan['pos'][1] - math.tan(angle)*scan['pos'][0]
          intersect_x = intersect_x + b/len(self.scans['y'])

        # Determine Y axis intersection with machine X axis based on new angle
        intersect_y = 0
        for scan in self.scans['x'] :
          b = scan['pos'][0] + math.tan(angle)*scan['pos'][1]
          intersect_y = intersect_y + b/len(self.scans['x'])

        # correct for tool radius (x_direction and y_direction are the signed
        # of the scan movement along the x resp. y axis, not the directions for
        # the scans used to define the respective axis!)
        intersect_x = intersect_x + y_direction*math.cos(angle)*self.tool_radius
        intersect_y = intersect_y + x_direction*math.cos(angle)*self.tool_radius

        # compute coordinate transform offsets
        self.offset[0] = (intersect_y - intersect_x * math.tan(angle)) /       \
                         (1 + pow(math.tan(angle), 2))
        self.offset[1] = self.offset[0]*math.tan(angle) + intersect_x

        # compute coordinate transform rotation matrix
        self.rot_mat = [ [ math.cos(angle), -math.sin(angle)],
                         [+math.sin(angle),  math.cos(angle)] ]

        gcmd.respond_info("Offsets: "+str(self.offset))
        gcmd.respond_info("Rotation matrix: "+str(self.rot_mat))

        gcmd.respond_info("New workpart transform computed. This will not be "
            + "saved into the config file. Re-issue COMPUTE_WORKPART command "
            + "after restart to restore the workpart transform!")


    def get_position(self):
        x, y, z, e = self.normal_transform.get_position()
        x = x - self.offset[0]
        y = y - self.offset[1]
        xn = x*self.rot_mat[0][0] + y*self.rot_mat[1][0]
        yn = x*self.rot_mat[0][1] + y*self.rot_mat[1][1]
        return [xn, yn, z, e]


    def move(self, newpos, speed):
        x, y, z, e = newpos
        xn = x*self.rot_mat[0][0] + y*self.rot_mat[0][1]
        yn = x*self.rot_mat[1][0] + y*self.rot_mat[1][1]
        xn = xn + self.offset[0]
        yn = yn + self.offset[1]
        self.normal_transform.move([xn, yn, z, e], speed)


def load_config(config):
    return WorkpartEdgeTouch(config)
