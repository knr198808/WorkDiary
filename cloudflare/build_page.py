# page/app.html, page/sw.js 를 서버 코드(app_page.js)로 묶음. 페이지를 고친 뒤 실행.
import json, os
d = os.path.dirname(os.path.abspath(__file__))
html = open(os.path.join(d, "page", "app.html"), encoding="utf-8").read()
sw = open(os.path.join(d, "page", "sw.js"), encoding="utf-8").read()
with open(os.path.join(d, "app_page.js"), "w", encoding="utf-8") as f:
    f.write("// 자동 생성 (build_page.py) — page/ 폴더의 파일을 고치세요\n")
    f.write("export const APP_HTML = " + json.dumps(html, ensure_ascii=False) + ";\n")
    f.write("export const SW_JS = " + json.dumps(sw, ensure_ascii=False) + ";\n")
print("app_page.js 생성")
