from pathlib import Path
from html import escape
from PIL import Image, ImageDraw, ImageFont
O=Path(__file__).resolve().parent
W,H=1500,1180
im=Image.new('RGB',(W,H),'white'); d=ImageDraw.Draw(im); svg=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}"><rect width="100%" height="100%" fill="white"/>']
def text(x,y,s,n=21,c='#203444'):
 f=ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf',n);d.text((x,y),s,font=f,fill=c);svg.append(f'<text x="{x}" y="{y+n*.9}" font-family="Arial" font-size="{n}" fill="{c}">{escape(s)}</text>')
def line(p,c='#263c4c',w=3):
 d.line(p,fill=c,width=w);svg.append(f'<polyline points="'+ ' '.join(f'{x},{y}' for x,y in p)+f'" fill="none" stroke="{c}" stroke-width="{w}"/>')
def box(x,y,w,h,c):
 d.rectangle((x,y,x+w,y+h),fill=c);svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{c}"/>')
def dot(x,y,r=5,c='#906e40'):
 d.ellipse((x-r,y-r,x+r,y+r),fill=c);svg.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{c}"/>')
text(40,25,'IR transmitter • perfboard layout for your placement',36)
text(40,76,'Same orientation as your photo: USB left, ESP32 antenna right, empty strip above.',23)
text(40,113,'NEW coordinates: A = topmost hole row; 1 = leftmost hole. Ignore the board’s printed labels.',22)
text(40,150,'Use the first 18 columns × 7 rows of the empty strip. Dry-fit parts before soldering.',22)
ends={'R1':('C8','C12'),'R2':('G7','G11'),'R3':('D5','D9'),'C1':('F2','F4'),'LED':('A12','A13')}
colors={'5V':'#c43c35','LED+':'#c77d00','collector':'#8446b0','base':'#237ec1','GND':'#263c4c'}
routes=[('5V',['F2','C2','C8']),('LED+',['C12','A12']),('collector',['A13','E13','E12']),('base',['G11','E11']),('base',['D9','D11','E11']),('GND',['F4','F5','D5']),('GND',['D5','E5','E10'])]
for panel,ox in enumerate([75,825]):
 mirror=bool(panel)
 def p(s):
  row=ord(s[0])-65;col=int(s[1:])-1
  return ox+(17-col if mirror else col)*32,310+row*42
 text(ox-25,220,'SOLDER SIDE • flipped left ↔ right' if mirror else 'COMPONENT SIDE • looking down',25)
 text(ox-25,256,'Keep edge A at the top when flipping.' if mirror else 'Parts go through these holes.',20)
 box(ox-20,290,585,300,'#f3dfba')
 for r in 'ABCDEFG':
  text(ox-45,p(r+'1')[1]-12,r,18)
 for c in range(1,19):
  x,y=p('A'+str(c));text(x-8,591,str(c),16)
  for r in 'ABCDEFG':dot(*p(r+str(c)),4)
 if mirror:
  for net,route in routes:line([p(s) for s in route],colors[net],5)
  for net,route in routes:
   for s in [route[0],route[-1]]:dot(*p(s),6,colors[net])
  for s,label in [('F2','5V'),('F4','GND'),('G7','GPIO4')]:
   x,y=p(s);dot(x,y,6,'#138356');text(x-20,y+10,label,16)
 else:
  for key,(a,b) in ends.items():
   x,y=p(a);xx,yy=p(b);line([(x,y),(xx,yy)],'#555555',4)
   if key.startswith('R'):
    box((x+xx)/2-32,y-10,64,20,'#edc785');text((x+xx)/2-35,y-36,{'R1':'270 Ω','R2':'470 Ω','R3':'10 kΩ'}[key],18)
   elif key=='C1':
    dot((x+xx)/2,y,26,'#438585');text(x-7,y+23,'+',20);text(xx-7,y+23,'−',20);text(x-20,y-55,'100 µF',18)
   else:
    dot((x+xx)/2,y-5,20,'#da8b9c');text(x-25,y-55,'IR LED → aim outward',18);text(x-8,y+15,'A',16);text(xx-7,y+15,'K',16)
   dot(x,y,5,'#132e3f');dot(xx,yy,5,'#132e3f')
  x,y=p('E10');box(x-12,y-17,88,34,'#303d48')
  for s,label in [('E10','E'),('E11','B'),('E12','C')]:
   x,y=p(s);dot(x,y,4,'white');text(x-6,y+22,label,17)
  text(p('E14')[0],p('E14')[1]-10,'PN2222A',17)
 text(ox-25,638,'ESP32 sits below this strip; use BOTH female header rows.',18)
text(40,700,'Placement / lead identities',27)
items=['270 Ω: C8–C12     |     470 Ω: G7–G11     |     10 kΩ: D5–D9',
       'IR LED: anode A12, cathode A13. Bend the LED to point beyond the board edge.',
       'Transistor: emitter E10, base E11, collector E12. Identify leads before forming them.',
       '100 µF: positive F2, negative F4. Gently adapt lead spacing; do not force the body.',
       'ESP32 header pad marked 5V → F2; GND → F4; GPIO4 (marked 4) → G7.']
for i,s in enumerate(items):text(40,746+i*36,s,22)
text(40,951,'Solder-side wires: insulated wire, stripped only at endpoints.',25)
text(40,991,'Bends and crossings are NOT junctions. Solder only the listed endpoints; pads are isolated.',21)
text(40,1028,'Keep bare wires away from all other header pads. No receiver, 3V3 connection or firmware change.',21)
text(40,1065,'Unplug USB and remove ESP32 before wiring. Check for shorts, then fit ESP32 and test.',21)
text(40,1102,'Header hole coordinates are intentionally omitted: the photo hides them. Follow PCB pin labels.',21)
svg.append('</svg>');(O/'samsung-ac-perfboard.svg').write_text('\n'.join(svg));im.save(O/'samsung-ac-perfboard.png')
