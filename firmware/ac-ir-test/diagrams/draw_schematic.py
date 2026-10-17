"""Generate the reviewed schematic as SVG and PNG; no third-party art assets."""
from pathlib import Path
from html import escape
from PIL import Image, ImageDraw, ImageFont
OUT = Path(__file__).resolve().parent
W,H=1600,1800
im=Image.new('RGB',(W,H),'#ffffff'); d=ImageDraw.Draw(im)
svg=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">', '<title>ESP32-S3 Samsung AC IR transmitter and receiver schematic</title>', '<rect width="1600" height="1800" fill="white"/>']
ink='#152836'; wire='#244858'; red='#b32936'; muted='#536773'
def line(pts,color=wire,width=4):
 d.line(pts,fill=color,width=width,joint='curve'); svg.append(f'<polyline points="{" ".join(f"{x},{y}" for x,y in pts)}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linejoin="round"/>')
def text(x,y,t,size=25,color=ink,bold=False):
 font=ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial'+(' Bold' if bold else '')+'.ttf',size)
 d.text((x,y),t,font=font,fill=color)
 svg.append(f'<text x="{x}" y="{y+size*.92}" font-family="Arial,sans-serif" font-size="{size}" fill="{color}" font-weight="{700 if bold else 400}">{escape(t)}</text>')
def rect(x,y,w,h,fill='white',stroke=ink,width=3):
 d.rectangle((x,y,x+w,y+h),fill=fill,outline=stroke,width=width)
 svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" stroke="{stroke}" stroke-width="{width}"/>')
def circle(x,y,r,fill='white',stroke=ink,width=3):
 d.ellipse((x-r,y-r,x+r,y+r),fill=fill,outline=stroke,width=width)
 svg.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{width}"/>')
def poly(pts,fill=ink):
 d.polygon(pts,fill=fill); svg.append(f'<polygon points="{" ".join(f"{x},{y}" for x,y in pts)}" fill="{fill}"/>')
def dot(x,y): circle(x,y,6,wire,wire,1)
def ground(x,y):
 line([(x,y),(x,y+15)]); line([(x-24,y+15),(x+24,y+15)]);line([(x-16,y+25),(x+16,y+25)]);line([(x-7,y+35),(x+7,y+35)])
def resistor_v(x,y,label):
 line([(x,y),(x,y+10)]); rect(x-12,y+10,24,48);line([(x,y+58),(x,y+70)]);text(x+30,y+19,label,24)
def arrow(x1,y1,x2,y2):
 import math
 line([(x1,y1),(x2,y2)],ink,3)
 a=math.atan2(y2-y1,x2-x1); l=14; w=6
 poly([(x2,y2),(x2-l*math.cos(a)+w*math.sin(a),y2-l*math.sin(a)-w*math.cos(a)),(x2-l*math.cos(a)-w*math.sin(a),y2-l*math.sin(a)+w*math.cos(a))])
text(65,45,'ESP32-S3 → Samsung AC',44,bold=True)
text(65,102,'USB powered • GPIO4: IR transmit • GPIO5: IR receive',26,color=muted)
# Main supply and controller block
line([(410,200),(1420,200)],red);text(430,160,'+5 V from USB-powered board',24,red,bold=True)
rect(65,350,310,500,fill='#f2f6f8')
text(100,388,'U1  ESP32-S3',30,bold=True);text(100,432,'WROOM-1 N16R8',23)
text(100,473,'USB power + serial',23,color=muted)
text(278,548,'5V',24,bold=True);line([(375,565),(410,565),(410,200)],red)
text(250,637,'GPIO4',24,bold=True);line([(375,650),(525,650)])
text(260,783,'GND',24,bold=True);line([(375,800),(410,800),(410,970),(1420,970)])
text(100,720,'Pin labels only;',21,color=muted);text(100,748,'not header positions.',21,color=muted)
# Named nets to receiver circuit below (same U1).
text(110,813,'3V3',22,bold=True);line([(140,850),(140,1025)])
text(104,1033,'3V3',23,bold=True)
text(210,813,'GPIO5',22,bold=True);line([(265,850),(265,1025)])
text(221,1033,'GPIO5',23,bold=True)
# Series resistors LED branch
line([(950,200),(950,320)],red);dot(950,200)
resistor_v(950,320,'R1  220 Ω')
text(980,374,'≥ 0.25 W',22,color=muted)
line([(950,390),(950,505)])
# LED diode triangle + cathode bar and outward light arrows
poly([(930,505),(970,505),(950,537)])
line([(928,540),(972,540)],ink);line([(950,540),(950,590)])
arrow(979,512,1007,484);arrow(989,535,1017,507)
text(1025,515,'D1  IR LED',26,bold=True);text(1025,550,'940 nm',23)
text(905,485,'A',22);text(905,541,'K',22)
# Base resistor and branch
line([(525,650),(555,650)]);rect(555,638,90,24);line([(645,650),(905,650)])
text(540,600,'R4  470 Ω',24)
dot(780,650);line([(780,650),(780,710)])
resistor_v(780,710,'R5  10 kΩ');line([(780,780),(780,970)]);dot(780,970)
text(525,788,'Base pull-down',23,color=muted);text(525,822,'R5 = 10 kΩ',23,color=muted)
# NPN symbol: base bar, collector, emitter outward arrow
circle(930,650,64)
line([(865,650),(905,650)])
line([(905,615),(905,685)],ink,5)
line([(905,632),(950,603),(950,590)])
line([(905,671),(950,702),(950,970)])
arrow(930,688,950,702)
text(875,650,'B',20);text(963,585,'C',21);text(963,704,'E',21)
text(1020,615,'Q1',25,bold=True);text(1020,650,'PN2222ATA',25,bold=True);text(1020,685,'NPN',23)
dot(950,970)
# Decoupling: capacitors each in parallel on supply
for x,lab,sub,polar in [(1240,'C1','100 µF / 25 V',True),(1420,'C2','100 nF',False)]:
 dot(x,200);line([(x,200),(x,385)])
 line([(x-30,385),(x+30,385)],ink,4)
 line([(x-30,410),(x+30,410)],ink,4)
 line([(x,410),(x,970)]);dot(x,970)
 label_x = x-145 if polar else x+45
 text(label_x,280,lab,25,bold=True);text(label_x,322,sub,22)
 if polar:
  text(x-55,355,'+',26,red,bold=True);text(x-54,409,'−',25)
# ground and lower annotations
ground(950,970);text(1010,998,'Common GND',24,bold=True)
# Receiver, connected to the same controller through named nets.
line([(65,1120),(1535,1120)],'#ccd6dc',2)
text(65,1160,'IR receiver / remote capture',32,bold=True)
text(65,1210,'Matching 3V3 and GPIO5 labels are electrically connected to U1 above.',23,color=muted)
rect(650,1320,310,225,fill='#f2f6f8')
text(680,1350,'U2  VS1838B',29,bold=True)
text(680,1392,'38 kHz receiver',23)
text(665,1440,'VCC',22,bold=True)
line([(650,1455),(440,1455),(440,1290)],red)
text(407,1254,'3V3',25,red,bold=True)
text(869,1464,'OUT',22,bold=True)
line([(960,1480),(1175,1480)]);text(1190,1464,'GPIO5',25,bold=True)
text(1170,1510,'Idle HIGH / active LOW',22,color=muted)
text(769,1508,'GND',22,bold=True)
line([(800,1545),(800,1610),(440,1610)])
line([(440,1455),(440,1510)]);dot(440,1455)
line([(410,1510),(470,1510)],ink,4);line([(410,1535),(470,1535)],ink,4)
line([(440,1535),(440,1610)])
text(295,1490,'C3',25,bold=True);text(295,1525,'100 nF',23)
ground(800,1610);text(850,1610,'Common GND',23)
arrow(1060,1340,1000,1375);arrow(1080,1380,1020,1415)
text(1135,1350,'IR from remote',24);text(1135,1384,'or test emitter',24)
text(65,1700,'C3 goes close to U2. Verify its physical pin order; this symbol uses functional pin labels.',24)
text(65,1740,'Keep the receiver on 3.3 V. R1 = 220 Ω; R5 = 10 kΩ. All grounds are common.',24,color=muted)
svg.append('</svg>')
(OUT/'samsung-ac-ir-schematic.svg').write_text('\n'.join(svg))
im.save(OUT/'samsung-ac-ir-schematic.png')

# Physical header reference plus the electrical schematic on one sheet.
# Source: Espressif DevKitC-1 v1.1 user guide, J1/J3 header tables.
schematic_image = im.copy()
schematic_svg = '\n'.join(svg[1:-1])
W,H=900,1800
im=Image.new('RGB',(W,H),'white'); d=ImageDraw.Draw(im)
svg=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">', '<title>ESP32-S3 DevKitC-1 physical header reference for AC IR test</title>', '<rect width="900" height="1800" fill="white"/>']
text(35,45,'ESP32-S3 board pinout',39,bold=True)
text(35,102,'DevKitC-1 reference • 44 pins • top view',25,color=muted)
text(35,155,'Antenna at top; USB connectors at bottom.',25)
text(35,197,'Match your board’s printed labels before wiring.',23,color=red,bold=True)
left=['3V3','3V3','RST / EN','4','5','6','7','15','16','17','18','8','3','46','9','10','11','12','13','14','5V','GND']
right=['GND','TX / 43','RX / 44','1','2','42','41','40','39','38','37 *','36 *','35 *','0','45','48','47','21','20','19','GND','GND']
rect(300,270,350,1100,fill='#f2f6f8')
rect(390,285,170,85,fill='#e1e9ed');text(411,310,'ANTENNA',23,bold=True)
text(310,390,'J1',22,bold=True);text(600,390,'J3',22,bold=True)
colors={0:'#9d2633',3:'#246f9c',4:'#6a429c',20:'#b32936',21:'#244858'}
labels={0:'3V3 → U2 VCC',3:'GPIO4 → R4, 470 Ω',4:'GPIO5 ← U2 OUT',20:'5V → R1 + C1/C2',21:'GND → common GND'}
for i,(l,r) in enumerate(zip(left,right)):
 y=430+i*39
 color=colors.get(i,ink)
 rect(286,y-9,20,20,fill=color if i in colors else '#d8e1e6')
 rect(644,y-9,20,20,fill='#d8e1e6')
 text(321,y-13,l,24,color=color,bold=i in colors)
 text(530,y-13,r,24,color='#936115' if '*' in r else ink)
 text(677,y-10,str(i+1),19,color=muted)
 if i in colors:
  line([(286,y),(220,y)],color,4)
  text(35,y-30,labels[i],21,color=color,bold=True)
 else:
  text(255,y-10,str(i+1),19,color=muted)
# Generic connector outlines: specific clone USB labels must be checked.
rect(340,1300,100,68,fill='#dde4e8');rect(510,1300,100,68,fill='#dde4e8')
text(360,1319,'USB',24);text(530,1319,'USB',24)
text(318,1390,'USB connector positions are illustrative.',21,color=muted)
text(35,1465,'Connections used in this circuit',27,bold=True)
text(35,1510,'J1: 1 = 3V3; 4 = GPIO4; 5 = GPIO5;',24)
text(35,1545,'21 = 5V; 22 = GND. Numbers count from the top.',24)
text(35,1600,'* GPIO35–37 are reserved for octal PSRAM on N16R8.',22,color=muted)
text(35,1640,'GPIO numbers and header positions are different concepts.',22,color=muted)
text(35,1680,'WROOM-1 identifies the module, not the carrier-board layout.',22,color=muted)
text(35,1720,'Reference: Espressif DevKitC-1 v1.1 J1/J3 header tables.',22,color=muted)
svg.append('</svg>')
(OUT/'esp32-s3-ir-pinout.svg').write_text('\n'.join(svg))
im.save(OUT/'esp32-s3-ir-pinout.png')
combined=Image.new('RGB',(2500,1800),'white')
combined.paste(im,(0,0));combined.paste(schematic_image,(900,0))
combined.save(OUT/'samsung-ac-ir-wiring.png')
combined_svg=['<svg xmlns="http://www.w3.org/2000/svg" width="2500" height="1800" viewBox="0 0 2500 1800">', '<title>ESP32-S3 physical pinout and Samsung AC IR circuit</title>', '\n'.join(svg[1:-1]), '<g transform="translate(900 0)">', schematic_svg, '</g></svg>']
(OUT/'samsung-ac-ir-wiring.svg').write_text('\n'.join(combined_svg))
