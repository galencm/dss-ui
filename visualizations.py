# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2018, Galen Curwen-McAdams

from PIL import Image as PILImage, ImageDraw, ImageColor
import uuid
import functools
import io

def project_dimensions(project, width=200, height=200, scale=1, filename=None):
    x_offset = 10
    y_offset = 10
    drawn_x = 0
    drawn_y = 0
    figure_spacing = 20
    fore_shorten = 0.5

    # width = width * 2 + depth * 2

    d = {}
    for dimension in ['width', 'height', 'depth']:
        try:
            d[dimension] = float(project[dimension]) * scale
            d["unscaled_" + dimension] = float(project[dimension])
        except Exception as ex:
            d[dimension]  = 0 * scale
            d["unscaled_" + dimension]  = 0

    try:
        d['unit'] = project['unit']
    except KeyError:
        d['unit'] = "None"

    needed_width = (d['width']* 3) + (d['depth'] * 3) + (figure_spacing * 2) + x_offset
    # add 50 for caption
    needed_height = (d['height'] + (d['depth'] * fore_shorten) + y_offset + 50)
    if width < (needed_width):
        width = int(needed_width)

    if height < (needed_height):
        height = int(needed_height)

    dimensions_image = PILImage.new('RGB', (width, height), (155, 155, 155, 255))
    draw = ImageDraw.Draw(dimensions_image, 'RGBA')

    # landscape layout, use drawn_x to increment figures

    # draw facing
    draw.rectangle([x_offset + drawn_x, y_offset, x_offset + drawn_x + d['width'], y_offset + d['height']], outline=(255, 255, 255, 255))
    drawn_x += x_offset + d['width']
    drawn_x += figure_spacing

    # draw side
    draw.rectangle([x_offset + drawn_x, y_offset, x_offset + drawn_x + d['depth'], y_offset + d['height']], outline=(255, 255, 255, 255))
    drawn_x += x_offset + d['depth']
    drawn_x += figure_spacing

    # draw perspective
    # top left angle line
    back_upper_left_corner = (x_offset + drawn_x, y_offset)
    fore_upper_left_corner = ((x_offset + drawn_x) + (d['depth'] * fore_shorten), y_offset + (d['depth'] * fore_shorten))
    draw.line([fore_upper_left_corner, back_upper_left_corner])
    # bottom left angle line
    back_lower_left_corner = (x_offset + drawn_x, y_offset + d['height'])
    fore_lower_left_corner = ((x_offset + drawn_x) + (d['depth'] * fore_shorten), (y_offset + d['height']) + (d['depth'] * fore_shorten))
    draw.line([fore_lower_left_corner, back_lower_left_corner])
    # top right angle line
    back_upper_right_corner = (x_offset + drawn_x + d['width'], y_offset)
    fore_upper_right_corner = ((x_offset + drawn_x + d['width']) + (d['depth'] * fore_shorten), y_offset + (d['depth'] * fore_shorten))
    draw.line([fore_upper_right_corner, back_upper_right_corner])
    # rear vertical line
    draw.line([back_upper_left_corner, back_lower_left_corner])
    # rear horizontal line
    draw.line([back_upper_left_corner, back_upper_right_corner])
    # foreground square, front
    draw.rectangle([fore_upper_left_corner, fore_upper_left_corner[0] + d['width'], fore_upper_left_corner[1] + d['height']], outline=(255, 255, 255, 255))
    # print dimensions at bottom of figure
    draw.text([x_offset, y_offset + d['height'] + 10], "{unscaled_width} x {unscaled_depth} x {unscaled_height} \nunits: {unit}".format(**d))

    # dimensions_image.show()
    if filename:
        image_filename = '/tmp/{}.jpg'.format(str(uuid.uuid4()))
        dimensions_image.save(image_filename)
        filename = image_filename

    file = io.BytesIO()
    extension = 'JPEG'
    dimensions_image.save(file, extension)
    dimensions_image.close()
    file.seek(0)

    return (filename, file)

def vertical_texture(draw, spacing, top, height, width):
    # draw mutable, so no return
    for space in range(0, width, round(width / spacing)):
        draw.line((space, top, space, top + height), width=2, fill=(255, 255, 255, 128))

def project_overview(project, width, height, filename=None, orientation='horizontal', step_offset=0, background_palette_field="", texturing=None, coloring=None, color_key=False):
    # the lattice ui uses a sequence broken into 
    # blocks of images for the accordion view
    #
    # this returns a single horizontal or vertical 
    # color coded strip of categories with an optional
    # key for category names / colors beneath

    # project is dict containing
    # categories: {"name1" : int expected, "name2"} #ordered
    # palette: {"name1":{"fill" : "", "border": ""}, "name2":...}
    if coloring is None:
        try:
            coloring = project['palette']
        except KeyError:
            coloring = {}

    sequence_steps = []
    try:
        for k,v in project['categories'].items():
            for step in range(v):
                sequence_steps.append(k)
    except KeyError:
        pass
    # fallback color schemes
    # catch 'None' and '*' for everything else
    if not 'None' in coloring:
        coloring['None'] = {}
        coloring['None']['fill'] = "darkgray"
        coloring['None']['border'] = (135,135,135,1)
    else:
        if not 'fill' in coloring['None']:
            coloring['None']['fill'] = "darkgray"
        if not 'border' in coloring['None']:
            coloring['None']['border'] = (135,135,135,1)

    if not '*' in coloring:
        coloring['*'] = {}
        coloring['*']['fill'] = "lightgray"
        coloring['*']['border'] = (223,223,223,1)
    else:
        if not 'fill' in coloring['*']:
            coloring['*']['fill'] = "lightgray"

        if not 'border' in coloring['*']:
            coloring['*']['border'] = (223,223,223,1)

    if color_key is True:
        color_key_padding = 20
    else:
        color_key_padding = 0

    overview_image = PILImage.new('RGB', (width, height + color_key_padding), (155, 155, 155, 255))
    draw = ImageDraw.Draw(overview_image, 'RGBA')

    print(coloring)
    draw_stack = []
    # use to label start and end of sequences
    last_step = False
    subcount = 0
    text_inset = 25
    color_keys = {}
    for step_num, step in enumerate(sequence_steps):
        if step is None:
            color = coloring['None']['fill']
            border_color = coloring['None']['border']
        else:
            try:
                if sequence_steps[step_num+1] != step:
                    last_step = True
                else:
                    last_step = False
            except:
                last_step = True
            color = coloring['*']['fill']
            border_color = coloring['*']['border']
            for k, v in coloring.items():
                #for key, value in step.items():
                    if k == step:
                        try:
                            if isinstance(coloring[k]['fill'], list):
                                color = tuple(coloring[k]['fill'])
                            else:
                                color = coloring[k]['fill']
                        except Exception as ex:
                            print(ex)
                            color = coloring['*']['fill']

                        try:
                            if isinstance(coloring[k]['border'], list):
                                border_color = tuple(coloring[k]['border'])
                            else:
                                border_color = coloring[k]['border']
                        except Exception as ex:
                            # print(ex)
                            border_color = coloring['*']['border']

                        if orientation == 'vertical':
                            stepwise = height / len(sequence_steps)
                            x1 = 0
                            y1 = stepwise * step_num
                            x2 = width
                            y2 = (stepwise * step_num) + stepwise
                            separator = functools.partial(draw.line, (0, y1, width, y1), fill=(255,255,255,55))
                        elif orientation == 'horizontal':
                            stepwise = width / len(sequence_steps)
                            y1 = 0
                            x1 = stepwise * step_num
                            y2 = height
                            x2 = (stepwise * step_num) + stepwise
                            separator = functools.partial(draw.line, (x1, 0, x1, height), fill=(255,255,255,55))

                        # get rgb of color to modify alpha if needed
                        if isinstance(color,str):
                            color = ImageColor.getrgb(color)

                        color_keys[step] = color
                        draw_call = functools.partial(draw.rectangle,(x1, y1, x2, y2), outline=border_color, fill=color)
                        draw_stack.append(draw_call)
                        draw_stack.append(separator)
                        #draw_stack.append(functools.partial(draw.line, (0, x1, 0, x2), fill=(255,255,255)))
                        subcount += 1
                        
                        if last_step:
                            draw_stack.append(functools.partial(draw.text, (x2-text_inset, y1), str(step_num + step_offset)+ "\n" + str(step_num + step_offset + 1) + "\n{}".format(subcount), (230, 230, 230,128)))
                            subcount = 0
                        break
        if texturing:
            try:
                if texturing[step_num] == 0:
                    # continuous draw vertical lines
                    draw_stack.append(functools.partial(vertical_texture, draw, 8, y1, stepwise, width))
                elif texturing[step_num] == -1:
                    # discontinuous
                    pass
            except IndexError:
                pass
        # draw cells
        for dc in draw_stack:
            dc()

    if color_key is True:
        key_offset = 5
        y_start = height + key_offset
        x_start = 0
        color_block_size = 10
        horizontal_padding = 10
        for color_name, color_value in color_keys.items():
            draw.rectangle((x_start, y_start ,x_start + color_block_size, y_start + color_block_size),fill=color_value)
            text = draw.text((x_start + color_block_size, y_start), color_name)
            text_width = draw.textsize(color_name)[0]
            print(y_start, height, color_key_padding)
            key_width = text_width + color_block_size + horizontal_padding
            if x_start + key_width > width:
                y_start += key_offset * 3
                x_start = 0
            else:
                x_start += key_width

    if filename:
        image_filename = '/tmp/{}.jpg'.format(str(uuid.uuid4()))
        overview_image.save(image_filename)
        filename = image_filename

    file = io.BytesIO()
    extension = 'JPEG'
    overview_image.save(file, extension)
    overview_image.close()
    file.seek(0)

    return (filename, file)
