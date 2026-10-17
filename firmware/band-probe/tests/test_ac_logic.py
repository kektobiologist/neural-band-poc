"""Compare native Samsung frames/timing against the working IRremoteESP8266 library.
Run after installing the pinned dependency in firmware/ac-ir-test with PlatformIO.
No keys, hardware, or device operations are used.
"""
from pathlib import Path
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parents[3]
LIB = ROOT / 'firmware/ac-ir-test/.pio/libdeps/esp32-s3/IRremoteESP8266'
MAIN = ROOT / 'firmware/band-probe/main'
with tempfile.TemporaryDirectory() as tmp:
    t = Path(tmp)
    (t/'check.cpp').write_text(r'''
#include <cassert>
#include <cstring>
#include <iostream>
#include "ir_Samsung.h"
extern "C" {
#include "ac_logic.h"
}
int main() {
  for (int temp=16;temp<=30;temp++) for (int on=0;on<2;on++) for (int ext=0;ext<2;ext++) {
    IRSamsungAc reference(4);
    reference.stateReset(true,false);
    reference.setMode(kSamsungAcCool); reference.setTemp(temp);
    reference.setFan(kSamsungAcFanAuto); reference.setSwing(false); reference.setSwingH(false);
    reference.setPower(on);
    uint8_t frame[21]; size_t size=ac_make_frame(on,temp,ext,frame);
    if (ext) reference.sendExtended();
    else reference._irsend.sendSamsungAC(reference.getRaw(),14);
    // Compare all emitted mark/space timings; last space includes the library gap.
    ac_pulse_t pulses[175]; size_t n=ac_make_pulses(frame,size,pulses);
    assert(n == (ext?175:117));
    assert(reference._irsend.last+1 == 2*n);
    for (size_t i=0;i<n;i++) {
      assert(reference._irsend.output[i*2] == pulses[i].mark_us);
      assert(reference._irsend.output[i*2+1] == pulses[i].space_us+(i==n-1?97114:0));
      assert(reference._irsend.freq[i*2] == 38000);
      assert(reference._irsend.duty[i*2] == 50);
    }
    assert(IRSamsungAc::validChecksum(frame,size));
  }
  ac_gesture_filter_t f = {};
  band_gesture_t e={1,1000000,2,0,2,false};
  assert(ac_map_gesture(&f,&e)==AC_ON);
  assert(ac_map_gesture(&f,&e)==AC_NONE); // replay
  e.timestamp_us+=100000; assert(ac_map_gesture(&f,&e)==AC_NONE);
  e.timestamp_us+=500000; e.synthetic=true; assert(ac_map_gesture(&f,&e)==AC_NONE);
  e.synthetic=false; e.finger=3; assert(ac_map_gesture(&f,&e)==AC_OFF);
  e.action=4; e.derived=0; assert(ac_map_gesture(&f,&e)==AC_NONE); // raw doubletap duplicate
  e.finger=1; e.action=9; assert(ac_map_gesture(&f,&e)==AC_UP);
  e.action=0; e.derived=8; assert(ac_map_gesture(&f,&e)==AC_NONE); // derived swipe duplicate
  e.action=8; e.derived=0; assert(ac_map_gesture(&f,&e)==AC_DOWN);
  e.action=7; assert(ac_map_gesture(&f,&e)==AC_NONE); // unassigned down
  e.action=9; e.synthetic=true; e.timestamp_us+=500000; assert(ac_map_gesture(&f,&e)==AC_NONE);
  e.synthetic=false; e.finger=2; assert(ac_map_gesture(&f,&e)==AC_NONE);
  std::cout << "PASS: all 60 power/temperature/length combinations match library pulse-for-pulse; gesture filtering passed\n";
}
''')
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I'+str(MAIN),'-c',str(MAIN/'ac_logic.c'),'-o',str(t/'logic.o')],check=True)
    subprocess.run(['c++','-std=c++11','-DUNIT_TEST','-D_IR_ENABLE_DEFAULT_=false','-DSEND_SAMSUNG_AC=true',
        '-ffunction-sections','-fdata-sections','-Wl,-dead_strip',
        '-I'+str(MAIN),'-I'+str(LIB/'src'),'-I'+str(LIB/'test'), str(t/'check.cpp'),str(t/'logic.o'),
        *[str(LIB/'src'/f) for f in ['ir_Samsung.cpp','IRsend.cpp','IRtimer.cpp','IRutils.cpp','IRtext.cpp']],
        '-o',str(t/'check')],check=True)
    subprocess.run([str(t/'check')],check=True)
