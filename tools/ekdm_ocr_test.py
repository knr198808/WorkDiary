# -*- coding: utf-8 -*-
"""F9 준비: 어깨동무 메인 목록에서 선택된 회원 줄을 글자 인식으로 읽어보는 테스트 (여러 방식 비교)"""
import os, sys, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ekdm_ocr

root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
print("5초 안에 어깨동무 메인 화면을 클릭하세요 (회원 한 명이 파랗게 선택된 상태로).")
for i in range(5, 0, -1):
    print(i)
    time.sleep(1)
hwnd = ekdm_ocr.user32.GetForegroundWindow()
lines = []
for mode, k in (("gray", 3), ("gray", 4), ("bin", 3)):
    t0 = time.time()
    try:
        r = ekdm_ocr.read_selected(hwnd, debug_dir=root, mode=mode, k=k)
        line = f"[{mode}{k}] {time.time() - t0:.1f}초  이름={r['name']!r}  전화={r['phone']!r}  원문={r['raw']!r}"
    except Exception as e:
        line = f"[{mode}{k}] 실패: {e}"
    print(line)
    lines.append(line)
with open(os.path.join(root, "ekdm_ocr_result.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("\n결과를 ekdm_ocr_result.txt 에 저장했습니다.")
input("Enter를 누르면 닫힙니다.")
