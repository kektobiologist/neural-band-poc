from pathlib import Path
from html import escape
from PIL import Image,ImageDraw,ImageFont
O=Path(__file__).resolve().parent;W,H=1600,1200
im=Image.new('RGB',(W,H),'#f8fafc');d=ImageDraw.Draw(im);svg=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}"><rect width="100%" height="100%" fill="#f8fafc"/>']
def text(x,y,s,n=22,c='#203444'):
 f=ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf',n);d.text((x,y),s,font=f,fill=c);svg.append(f'<text x="{x}" y="{y+n*.9}" font-family="Arial" font-size="{n}" fill="{c}">{escape(s)}</text>')
def box(x,y,w,h,c):
 d.rectangle((x,y,x+w,y+h),fill=c);svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{c}"/>')
def line(p,c='#334155',w=4):
 d.line(p,fill=c,width=w);svg.append('<polyline points="'+' '.join(f'{x},{y}' for x,y in p)+f'" fill="none" stroke="{c}" stroke-width="{w}"/>')
def dot(x,y,r=5,c='#987344'):
 d.ellipse((x-r,y-r,x+r,y+r),fill=c);svg.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{c}"/>')
text(45,25,'Your complete transmitter board',38)
text(45,77,'Component-side view • same orientation as your photo • USB left, antenna right',25)
text(45,118,'Colored lines show electrical connections; install these insulated wires on the underside.',23)
ox,oy,dx,dy=125,230,45,32
# Whole 24 by 18 hole field. Header locations illustrative, not measured from obscured holes.
box(85,185,1120,645,'#d6ad70')
for r in range(18):
 for c in range(24):dot(ox+c*dx,oy+r*dy,4,'#916b36')
for x,y in [(105,205),(1185,205),(105,805),(1185,805)]:dot(x,y,11,'#f8fafc')
def p(s):return ox+(int(s[1:])-1)*dx,oy+(ord(s[0])-65)*dy
for c in range(1,19):text(p('A'+str(c))[0]-8,200,str(c),15)
for r in 'ABCDEFG':text(97,p(r+'1')[1]-9,r,16)
# ESP32 and sockets, positioned as in photo, body horizontal.
box(137,507,1060,41,'#202c36');box(137,757,1060,41,'#202c36')
box(143,521,1048,261,'#267b5c')
# two 22-contact rows at illustrative pitch
pins=['GND','5V','14','13','12','11','10','9','46','3','8','18','17','16','15','7','6','5','4','RST','3V3','3V3']
xs=[165+i*47 for i in range(22)]
for x,label in zip(xs,pins):
 dot(x,535,9,'#d8dfe2');dot(x,535,4,'#53616b');text(x-14,552,label,14,'white')
 dot(x,770,8,'#d8dfe2')
box(103,580,128,66,'#c8d0d5');box(103,682,128,66,'#c8d0d5')
text(112,600,'USB',22);text(112,702,'UART',20)
box(810,590,278,146,'#c6c9c5');text(830,620,'ESP32-S3',30);text(830,665,'WROOM-1',26)
box(1088,583,155,160,'#263440');text(1100,625,'ANTENNA',19,'white')
text(370,635,'ESP32 on two female headers',26,'white')
text(370,677,'Removable • no receiver circuit',21,'white')
# Wires behind parts: exact strip positions from previous drawing.
red='#c73535';blue='#1673c9';ground='#253747';orange='#cb8100';purple='#8951b2'
routes=[(red,['F2','C2','C8']),(orange,['C12','A12']),(purple,['A13','E13','E12']),(blue,['G11','E11']),(blue,['D9','D11','E11']),(ground,['F4','F5','D5']),(ground,['D5','E5','E10'])]
for color,route in routes:
 line([p(s) for s in route],color,5)
 for s in (route[0],route[-1]):dot(*p(s),6,color)
# Three header wires, beneath ESP board when needed. Route across clear gap.
line([(xs[1],535),(xs[1],484),(p('F2')[0],484),p('F2')],red,6)
line([(xs[0],535),(xs[0],470),(p('F4')[0],470),p('F4')],ground,6)
line([(xs[18],535),(xs[18],451),(p('G7')[0],451),p('G7')],blue,6)
for i,col in [(0,ground),(1,red),(18,blue)]:dot(xs[i],535,9,col)
text(110,845,'GND',23,ground);text(220,845,'5V',23,red);text(865,845,'4 = GPIO4',23,blue)
# component bodies and leads
for a,b,label in [('C8','C12','270 Ω'),('D5','D9','10 kΩ'),('G7','G11','470 Ω')]:
 x,y=p(a);xx,yy=p(b);line([(x,y),(xx,yy)],'#65676c',4);box((x+xx)/2-36,y-10,72,20,'#f3d29b');text((x+xx)/2-35,y-39,label,21)
 for s in [a,b]:dot(*p(s),5,'#273744')
x,y=p('F2');xx,_=p('F4');line([(x,y),(xx,y)],'#555555',4);dot((x+xx)/2,y,28,'#387b83');text(x-8,y-24,'+',22);text(xx-8,y-24,'−',22);text(x-15,y+33,'100 µF',20)
# LED viewed from above, extend out at top
x,y=p('A12');xx,_=p('A13');line([(x,y),(x,y-33),(xx,y-33),(xx,y)],'#555555',3);dot((x+xx)/2,y-35,23,'#bb5966');text(x-3,y+11,'A',17);text(xx-4,y+11,'K',17)
text(x-50,160,'IR LED • aim outward',21)
x,y=p('E10');box(x-13,y-16,116,32,'#263440')
for s,t in [('E10','E'),('E11','B'),('E12','C')]:
 x,y=p(s);dot(x,y,4,'white');text(x-6,y+20,t,17)
text(p('E14')[0],p('E14')[1]-10,'PN2222ATA',19)
# right explanatory key
text(1260,210,'Three wires',25)
for j,(label,color) in enumerate([('5V → F2',red),('GND → F4',ground),('GPIO4 → G7',blue)]):
 line([(1265,270+j*55),(1300,270+j*55)],color,5);text(1310,255+j*55,label,21,color)
text(1250,455,'Headers:',23)
text(1250,492,'solder both rows',20)
text(1250,525,'for support.',20)
text(1250,595,'Keep antenna',20)
text(1250,628,'area clear.',20)
text(45,912,'How to read this drawing',28)
text(45,959,'• A–G / 1–18 are the NEW coordinates from the earlier strip diagram, not the printed board labels.',22)
text(45,1000,'• ESP32/header position is illustrative: use actual pads marked GND, 5V and 4, not drawn hole positions.',22)
text(45,1041,'• Only wire endpoints connect. Crossings and bends do not connect to the pads beneath them.',22)
text(45,1082,'• Identify transistor E/B/C before fitting. Capacitor + goes to 5V; − goes to GND.',22)
text(45,1123,'• Remove ESP32 and unplug USB while wiring. Dry-fit components and check clearances first.',22)
svg.append('</svg>');(O/'samsung-ac-perfboard-full.svg').write_text('\n'.join(svg));im.save(O/'samsung-ac-perfboard-full.png')
