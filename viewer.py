from kivy.uix.scatter import Scatter
from kivy.app import App
from kivy.lang import Builder
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.logger import Logger, LOG_LEVELS
from kivy.graphics import Color, Line, Scale, Translate, PopMatrix, PushMatrix, Rectangle
from kivy.graphics import InstructionGroup
from kivy.properties import NumericProperty
from kivy.graphics.transformation import Matrix
from kivy.core.window import Window

import logging
import sys
import re
import math

Builder.load_string('''

<GcodeViewerScreen>:
    #on_enter: self.parse_gcode_file(app.gcode_file, 1, True)
    BoxLayout:
        orientation: 'vertical'
        BoxLayout:
            pos_hint: {'top': 1}
            Scatter:
                pos_hint: {'top': 1}
                id: surface
                do_rotation: False
                canvas.before:
                    Color:
                        rgb: 1, 1, 1, 1
                    Rectangle:
                        size: self.size

        BoxLayout:
            orientation: 'horizontal'
            size_hint_y: None
            height: 40
            Label:
                canvas.before:
                    Color:
                        rgb: 0, 1, 0, 1
                    Rectangle:
                        size: self.size
                id: z_value
                text: 'Z{}'.format(round(root.current_z, 1))
                size_hint_x: None
                width: self.texture_size[0]
            Button:
                text: 'First Layer'
                on_press: root.parse_gcode_file(app.gcode_file, 1, True)
            Button:
                text: 'Prev Layer'
                on_press: root.prev_layer()
            Button:
                text: 'Next Layer'
                on_press: root.next_layer()
            Button:
                text: 'Clear'
                on_press: root.clear()


<StartScreen>:
    on_leave: print('leaving start')
    Button:
        text: 'press me'
        on_press: root.manager.current = 'gcode'
''')


class GcodeViewerScreen(Screen):
    current_z= NumericProperty(0)

    def __init__(self, **kwargs):
        super(GcodeViewerScreen, self).__init__(**kwargs)
        self.app = App.get_running_app()
        self.last_file_pos= None
        self.canv = InstructionGroup()
        self.ids.surface.canvas.add(self.canv)
        self.transform= self.ids.surface.transform
        self.bind(pos=self._redraw, size=self._redraw)
        self.last_target_layer= 0

    def _redraw(self, instance, value):
        self.ids.surface.canvas.add(self.canv)

    def clear(self):
        self.canv.clear()
        self.ids.surface.canvas.remove(self.canv)

    def next_layer(self):
        self.parse_gcode_file(self.app.gcode_file, self.last_target_layer+1, True)

    def prev_layer(self):
        n= 1 if self.last_target_layer <= 1 else self.last_target_layer-1
        self.parse_gcode_file(self.app.gcode_file, n, True)

    extract_gcode= re.compile("(G|X|Y|Z|I|J|K|E)(-?\d*\.?\d+\.?)")
    def parse_gcode_file(self, fn, target_layer= 0, one_layer= False):
        # open file parse gcode and draw
        Logger.debug("GcodeViewerScreen: parsing file {}". format(fn))
        lastpos= [0,0,-1] # XYZ
        lastz= -1
        laste= 0
        layer= 0
        last_gcode= -1
        points= []
        max_x= float('nan')
        max_y= float('nan')
        min_x= float('nan')
        min_y= float('nan')
        has_e= False
        self.last_target_layer= target_layer

        # reset scale and translation
        m= Matrix()
        m.identity()
        self.ids.surface.transform= m

        # remove all instructions from canvas
        self.canv.clear()

        self.canv.add(PushMatrix())

        with open(fn) as f:
            # if self.last_file_pos:
            #     # jump to last read position
            #     f.seek(self.last_file_pos)
            #     self.last_file_pos= None
            #     print('Jumped to Saved position: {}'.format(self.last_file_pos))

            for l in f:
                l = l.strip()
                if not l: continue
                if l.startswith(';'): continue
                p= l.find(';')
                if p >= 0: l= l[:p]
                matches = self.extract_gcode.findall(l)
                #print(matches)
                d= dict((m[0], float(m[1])) for m in matches)

                # ignore lines with no G
                if 'G' not in d: continue

                # G92 E0 resets E
                if 'G' in d and d['G'] == 92 and 'E' in d:
                    laste= float(d['E'])
                    has_e= True

                # only deal with G0/1/2/3
                if d['G'] > 3: continue

                # TODO handle first move when lastpso is not valid yet

                # see if it is 3d printing (ie has an E axis on a G1)
                if not has_e and ('E' in d and 'G' in d and d['G'] == 1): has_e= True

                x= lastpos[0] if 'X' not in d else float(d['X'])
                y= lastpos[1] if 'Y' not in d else float(d['Y'])
                z= lastpos[2] if 'Z' not in d else float(d['Z'])
                i= 0.0 if 'I' not in d else float(d['I'])
                j= 0.0 if 'J' not in d else float(d['J'])

                e= laste if 'E' not in d else float(d['E'])

                # handle layers (when Z changes)
                if lastz < 0 and z > 0:
                    # first layer
                    lastz= z
                    layer= 1

                if z > lastz:
                    # count layers
                    layer += 1
                    lastz= z

                # wait until we get to the requested layer
                if layer < target_layer:
                    continue

                if layer > target_layer and one_layer:
                    # FIXME for some reason this does not work, -- not counting layers
                    #self.last_file_pos= f.tell()
                    #print('Saved position: {}'.format(self.last_file_pos))
                    self.current_z= lastpos[2]
                    break

                # find bounding box
                if math.isnan(min_x) or x < min_x: min_x= x
                if math.isnan(min_y) or y < min_y: min_y= y
                if math.isnan(max_x) or x > max_x: max_x= x
                if math.isnan(max_y) or y > max_y: max_y= y

                gcode= d['G']

                # TODO accumulating vertices is more efficient but seems to not work at some point
                # if last_gcode != gcode or (gcode == 1 and has_e and 'E' not in d):
                #     # flush vertices
                #     if points:
                #         self.ids.surface.canvas.add(Color(0, 0, 0))
                #         self.ids.surface.canvas.add(Line(points=points, width= 1, cap='none', joint='none'))
                #         points= []
                #     last_gcode= gcode


                # in slicer generated files there is no G0 so we need a way to know when to draw, so if there is an E then draw else don't
                if gcode == 0:
                    #print("move to: {}, {}, {}".format(x, y, z))
                    # draw moves in red
                    self.canv.add(Color(1, 0, 0))
                    self.canv.add(Line(points=[lastpos[0], lastpos[1], x, y], width= 1, cap='none', joint='none'))

                elif gcode == 1:
                    if ('X' in d or 'Y' in d):
                        # for 3d printers (has_e) only draw if there is an E
                        if not has_e or 'E' in d:
                            #print("draw to: {}, {}, {}".format(x, y, z))
                            # if len(points) < 2:
                            #     points.append(lastpos[0])
                            #     points.append(lastpos[1])

                            # points.append(x)
                            # points.append(y)
                            # self.canv.add(Line(points=points, width= 1, cap='none', joint='none'))
                            # points= []
                            # if we collect points then use above
                            self.canv.add(Color(0, 0, 0))
                            self.canv.add(Line(points=[lastpos[0], lastpos[1], x, y], width= 1, cap='none', joint='none'))

                        else:
                            # treat as G0 and draw moves in red
                            #print("move to: {}, {}, {}".format(x, y, z))
                            self.canv.add(Color(1, 0, 0))
                            self.canv.add(Line(points=[lastpos[0], lastpos[1], x, y], width= 1, cap='none', joint='none'))

                elif gcode in [2, 3]:
                    # arc starts at lastpos, center is relative to start I,J, ends at X,Y if specified otherwise 360
                    r= math.hypot(i, j)
                    w= r*2
                    h= r*2
                    cx= round(lastpos[0]+i, 4)
                    cy= round(lastpos[1]+j, 4)
                    sx= cx - r
                    sy= cy - r
                    ast= 0
                    aen= 360
                    #print(r, cx, cy)
                    #print(lastpos, x, y)
                    # if XY specified then it is an arc
                    if 'X' in d or 'Y' in d:
                        # arc start angle
                        if lastpos[0] < cx and lastpos[1] <= cy:
                            rad= round(abs(i)/r, 4)
                            ast= -90 - math.degrees(math.acos(round(rad, 4)))
                        elif lastpos[0] < cx and lastpos[1] > cy:
                            rad= round(abs(i)/r, 4)
                            ast= -math.degrees(math.acos(round(rad, 4)))
                        elif lastpos[0] >= cx and lastpos[1] <= cy:
                            rad= round(abs(j)/r, 4)
                            ast= 180 - math.degrees(math.acos(round(rad, 4)))
                        else:
                            rad= round(abs(j)/r, 4)
                            ast= math.degrees(math.acos(round(rad, 4)))

                        # arc end angle
                        dx= round(x-cx, 4)
                        dy= round(y-cy, 4)
                        #print(dx, dy)
                        if dx < 0 and dy > 0:
                            rad= round(abs(dx)/r, 4)
                            aen= -math.degrees(math.acos(round(rad, 4)))
                        elif dx < 0 and dy <= 0:
                            rad= round(abs(dx)/r, 4)
                            aen= -90-math.degrees(math.acos(round(rad, 4)))
                        elif dx >= 0 and dy <= 0:
                            rad= round(abs(dy)/r, 4)
                            aen= 180-math.degrees(math.acos(round(rad, 4)))
                        else:
                            rad= round(abs(dy)/r, 4)
                            aen= math.degrees(math.acos(round(rad, 4)))

                        #print(ast, aen)
                        if gcode == 2 and aen < ast:
                            aen += 360
                        if gcode == 3 and ast < aen: aen= aen-360

                        #print(ast, aen)

                    self.canv.add(Color(0, 0, 0))
                    self.canv.add(Line(ellipse=(sx, sy, w, h, ast, aen), width=1, cap= 'none', joint='round'))

                # always remember last position
                lastpos= [x, y, z]

        # center the drawing and scale it
        dx= max_x-min_x
        dy= max_y-min_y

        # pad by a few pixels
        dx += 4
        dy += 4

        # add in the translation
        self.canv.insert(1, Translate(self.ids.surface.center[0]-min_x+1-dx/2, self.ids.surface.center[1]-min_y+1-dy/2))

        # scale the drawing to fit the screen
        if dx > dy:
            scale= self.ids.surface.width/dx
            if dy*scale > self.ids.surface.height:
                scale *= self.ids.surface.height/(dy*scale)
        else:
            scale= self.ids.surface.height/dy
            if dx*scale > self.ids.surface.width:
                scale *= self.ids.surface.width/(dx*scale)

        Logger.debug("Size: {}, Scale by {}".format((dx, dy), scale))
        self.canv.insert(2, Scale(scale))
        self.canv.add(PopMatrix())

        # not sure why we need to do this
        self.ids.surface.top= Window.height


class StartScreen(Screen):
    pass

class GcodeViewerApp(App):
    def __init__(self, **kwargs):
        super(GcodeViewerApp, self).__init__(**kwargs)
        if len(sys.argv) > 1:
            self.gcode_file= sys.argv[1]
        else:
            self.gcode_file= 'tests/test.gcode' #'circle-test.g'

    def build(self):
        self.sm = ScreenManager()
        self.sm.add_widget(StartScreen(name='start'))
        self.sm.add_widget(GcodeViewerScreen(name='gcode'))
        level = LOG_LEVELS.get('debug')
        Logger.setLevel(level=level)
        #logging.getLogger().setLevel(logging.DEBUG)
        return self.sm


GcodeViewerApp().run()
