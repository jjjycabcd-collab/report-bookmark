import streamlit as st
import fitz  # PyMuPDF
import re
import os
import unicodedata
import tempfile
import time

# ==========================================
# [스트림릿 웹 전용 헬퍼 함수] 로그 색상 렌더링 및 영역 분리
# ==========================================
def format_final_logs(logs, compare_logs=None):
    # 개행 문자로 합쳐진 로그들을 한 줄씩 깔끔하게 분리
    flat_logs = []
    for item in logs:
        flat_logs.extend(str(item).split('\n'))
        
    flat_compare = set()
    if compare_logs:
        for item in compare_logs:
            flat_compare.update(str(item).split('\n'))

    progress_logs = []
    tree_logs = []
    is_tree_part = False
    
    # 5단계(책갈피 구성)를 기준으로 위/아래 로그를 두 그룹으로 나눔
    for line in flat_logs:
        if "5. 요약문 등 유령항목 단일화" in line:
            is_tree_part = True
            
        if is_tree_part:
            tree_logs.append(line)
        else:
            progress_logs.append(line)

    # HTML 블록 생성 헬퍼 함수
    def build_html(log_lines, max_height=None, is_terminal=False, is_tree=False):
        if not log_lines: return ""
        formatted = []
        for line in log_lines:
            out_line = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") # HTML 이스케이프
            
            is_diff = False
            if flat_compare and is_tree:
                if line not in flat_compare:
                    is_diff = True
            
            # [점검] 키워드는 무조건 '붉은색' 처리
            if "[점검]" in out_line:
                out_line = out_line.replace("[점검]", "<span style='color:red; font-weight:bold;'>[점검]</span>")
            
            # 차이점은 '파란색' 처리
            if is_diff:
                out_line = f"<span style='color:blue; font-weight:bold;'>{out_line}</span>"
                
            formatted.append(out_line)
            
        height_css = f"max-height: {max_height}; overflow-y: auto;" if max_height else "overflow-y: auto;"
        
        # 터미널 모드일 경우 검은 바탕에 흰 글씨 적용
        if is_terminal:
            css = f"font-family: monospace; white-space: pre; overflow-x: auto; {height_css} font-size: 14px; background-color: #1e1e1e; color: #ffffff; padding: 1rem; border-radius: 0.5rem; margin-bottom: 10px;"
        else:
            css = f"font-family: monospace; white-space: pre; overflow-x: auto; {height_css} font-size: 14px; background-color: rgba(128, 128, 128, 0.1); padding: 1rem; border-radius: 0.5rem; margin-bottom: 10px;"
            
        return f"<div style='{css}'>" + "\n".join(formatted) + "</div>"

    # 1~4 단계 로그는 150px로 작게 고정 (스크롤), 터미널 테마 적용
    html_progress = build_html(progress_logs, max_height="150px", is_terminal=True, is_tree=False)
    # 5 단계 이후(책갈피 트리) 로그는 600px로 넓게 보이도록 처리 (기존 유지)
    html_tree = build_html(tree_logs, max_height="600px", is_terminal=False, is_tree=True)

    return html_progress + html_tree

# ==========================================
# [스트림릿 로깅 클래스]
# ==========================================
class StreamlitLogger:
    def __init__(self, container=None):
        self.logs = []
        self.container = container or st
        self.placeholder = self.container.empty()
    
    def print(self, *args, **kwargs):
        msg = " ".join(map(str, args))
        self.logs.append(msg)
        # 실행 중에도 터미널 느낌(검은 바탕/흰 글씨)의 스크롤 박스로 실시간 출력
        safe_logs = [line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") for line in self.logs]
        css = "font-family: monospace; white-space: pre; overflow-x: auto; max-height: 150px; overflow-y: auto; font-size: 14px; background-color: #1e1e1e; color: #ffffff; padding: 1rem; border-radius: 0.5rem; margin-bottom: 10px;"
        self.placeholder.markdown(f"<div style='{css}'>" + "\n".join(safe_logs) + "</div>", unsafe_allow_html=True)
        
    def finalize(self, compare_logs=None):
        # 처리가 끝나면 HTML 서식(색상 하이라이트)을 적용하여 화면 고정
        formatted_html = format_final_logs(self.logs, compare_logs)
        self.placeholder.markdown(formatted_html, unsafe_allow_html=True)

# ==========================================
# 유사도 검사 라이브러리 지원
# ==========================================
try:
    from rapidfuzz import fuzz
    HAS_RAPIDFUZZ = True
except ImportError:
    import difflib
    HAS_RAPIDFUZZ = False

def get_ratio(s1, s2):
    if HAS_RAPIDFUZZ:
        return fuzz.ratio(s1, s2) / 100.0
    return difflib.SequenceMatcher(None, s1, s2).ratio()

# ==========================================
# 정규표현식 및 상수 사전 컴파일
# ==========================================
CLEAN_PATTERN = re.compile(r'[^a-zA-Z0-9가-힣]')
TOC_PATTERN = re.compile(r'^(.+?)\s*(?:[\.·_-]{2,}|\||\s+)\s*(\d+)\s*$', re.MULTILINE)

KOR_IDX = "가나다라마바사아자차카타파하"

CANDIDATE_PATTERN = re.compile(
    rf'^\s*('
    rf'제\s*\d+\s*[장절][\.\:]?(?:\s+|$)|'
    rf'<?\[?(?:붙임|별첨|부록)\s*\d*\]?(?:\s+|$)|'
    rf'<?\s*\[?\s*(?:(?:별\s*도\s*)?제\s*출\s*(?:문|물)|(?:보\s*고\s*서\s*)?요\s*약\s*서|(?:연\s*구\s*결\s*과\s*)?요\s*약\s*문|표\s*지|참\s*고\s*문\s*헌|[Ss]\s*[Uu]\s*[Mm]\s*[Mm]\s*[Aa]\s*[Rr]\s*[Yy]|[Cc]\s*[Oo]\s*[Nn]\s*[Tt]\s*[Ee]\s*[Nn]\s*[Tt]\s*[Ss]?|목\s*차)\s*\]?\s*>?(?:\s+|$)|'
    rf'[1-9]\d*(?:\.\d+)+[\.\)]?(?:\s+|$)|'
    rf'[1-9]\d*\.(?:\s+|$)|'
    rf'[1-9]\d*(?=\s+[가-힣a-zA-Z])|'
    rf'[{KOR_IDX}][\.\)）]\s*|'
    rf'[1-9]\d*(?:-\d+)+[\.\)]?(?:\s+|$)|'
    rf'[1-9]\d*[\)）](?:\s+|$)|'
    rf'\([1-9]\d*\)\s*|'
    rf'\([{KOR_IDX}]\)\s*|'
    rf'[A-Za-z][\.\)](?:\s+|$)'
    rf')'
)

PREFIX_STRIP_PATTERN = re.compile(rf'^\s*(Chapter\s*\d+|Section\s*\d+|제\s*\d+\s*[장절]|<?\s*\[?\s*(?:(?:별\s*도\s*)?제\s*출\s*(?:문|물)|(?:보\s*고\s*서\s*)?요\s*약\s*서|(?:연\s*구\s*결\s*과\s*)?요\s*약\s*문|표\s*지|참\s*고\s*문\s*헌|[Ss]\s*[Uu]\s*[Mm]\s*[Mm]\s*[Aa]\s*[Rr]\s*[Yy]|[Cc]\s*[Oo]\s*[Nn]\s*[Tt]\s*[Ee]\s*[Nn]\s*[Tt]\s*[Ss]?|목\s*차)\s*\]?\s*>?|<?\[?(?:붙임|별첨|부록)\s*\d*\]?>?|[{KOR_IDX}]|[1-9]\d*(?:\.\d+)*|(?:\d+-)+\d+|\([1-9]\d*\)|\([{KOR_IDX}]\)|[{KOR_IDX}][\)）]|\d+|[A-Za-z])\s*[\.\:\)）]?\s*', re.IGNORECASE)

KOR_CHARS = list(KOR_IDX)
KOR_MAP = {k: v + 1 for v, k in enumerate(KOR_CHARS)}

class PageCache:
    def __init__(self, doc, exclude_footnotes=False):
        self.doc = doc
        self.exclude_footnotes = exclude_footnotes
        self.text_cache = {}
        self.dict_cache = {}
        self.blocks_cache = {}
        self.exclude_bboxes_cache = {}
        self.valid_lines_cache = {}

    def get_text(self, p_idx):
        if p_idx not in self.text_cache: self.text_cache[p_idx] = self.doc[p_idx].get_text("text")
        return self.text_cache[p_idx]

    def get_dict(self, p_idx):
        if p_idx not in self.dict_cache: self.dict_cache[p_idx] = self.doc[p_idx].get_text("dict")
        return self.dict_cache[p_idx]

    def get_blocks(self, p_idx):
        if p_idx not in self.blocks_cache: self.blocks_cache[p_idx] = self.doc[p_idx].get_text("blocks")
        return self.blocks_cache[p_idx]
        
    def get_exclude_bboxes(self, p_idx):
        if p_idx not in self.exclude_bboxes_cache:
            page = self.doc[p_idx]
            bboxes = []
            for t in page.find_tables():
                if t.row_count >= 3 or t.col_count >= 3: bboxes.append(fitz.Rect(t.bbox))
            self.exclude_bboxes_cache[p_idx] = bboxes
        return self.exclude_bboxes_cache[p_idx]

    def get_valid_lines(self, p_idx):
        if p_idx not in self.valid_lines_cache:
            lines_data = []
            dict_data = self.get_dict(p_idx)
            exclude_bboxes = self.get_exclude_bboxes(p_idx)
            page_height = self.doc[p_idx].rect.height
            
            for b in dict_data.get("blocks", []):
                if b.get("type") != 0: continue
                block_spans = []
                for l in b.get("lines", []):
                    for s in l.get("spans", []): block_spans.append(s.get("text", ""))
                full_block_text = fix_broken_characters("".join(block_spans).replace('\n', ' ').strip())
                
                clean_block_for_check = full_block_text.replace(" ", "")
                if any(fs in clean_block_for_check for fs in ["이보고서는", "발표하는때에는", "국가과학기술기밀"]): continue  
                    
                is_desc = bool(re.search(r'(습니다|입니다|합니다|됩니다|바랍니다|시오|세요|할 것|한다|된다|이다|있다|없다|같다|기대된다|판단된다|보인다|수 있다|수 있음|진행함|확인함|관찰함|측정함|평가함|도출함|사용함|나타남|수행함|제조함|분석함|계산함|시행하였다)\.?\s*$', full_block_text))
                if re.search(r'[\.·]{4,}', full_block_text): continue
                
                for l in b.get("lines", []):
                    line_rect = fitz.Rect(l["bbox"])
                    if self.exclude_footnotes and line_rect.y0 > page_height * 0.85:
                        temp_text = "".join([s.get("text", "") for s in l.get("spans", [])]).strip()
                        if re.match(r'^\s*[1-9]\d*[\)\.]', temp_text): continue
                            
                    line_center = fitz.Point((line_rect.x0 + line_rect.x1) / 2, (line_rect.y0 + line_rect.y1) / 2)
                    if any(tb.contains(line_center) for tb in exclude_bboxes): continue
                        
                    text, last_x1, max_size, main_flags, main_color = "", -1, 0.0, 0, 0
                    for s in l.get("spans", []):
                        span_text, s_x0 = s.get("text", ""), s["bbox"][0]
                        if last_x1 != -1 and s_x0 - last_x1 > 3.0 and not text.endswith(' ') and not span_text.startswith(' '): text += " "
                        text += span_text
                        last_x1 = s["bbox"][2]
                        if s.get("size", 0.0) > max_size: 
                            max_size = s.get("size", 0.0)
                            main_flags = s.get("flags", 0)
                            main_color = s.get("color", 0)
                            
                    text = fix_broken_characters(text.strip())
                    if text and not re.search(r'[\.·]{4,}', text):
                        lines_data.append({'text': text, 'y0': l["bbox"][1], 'max_size': max_size, 'flags': main_flags, 'color': main_color, 'is_desc': is_desc})
            self.valid_lines_cache[p_idx] = lines_data
        return self.valid_lines_cache[p_idx]

def fix_broken_characters(text):
    if not text: return text
    text = unicodedata.normalize('NFC', text)
    text = text.replace('\uf85e', '·').replace('獜', '·')      
    return re.sub(r'(?<=[가-힣])[^\s가-힣\x20-\x7E·]+(?=[가-힣])', '·', text)

def parse_custom_format(fmt):
    if not fmt: return None
    escaped = re.escape(fmt.strip())
    escaped = escaped.replace('1', r'[1-9]\d*')
    escaped = escaped.replace('가', rf'[{KOR_IDX}]')
    escaped = escaped.replace('A', r'[A-Z]')
    escaped = escaped.replace('a', r'[a-z]')
    return re.compile(rf'^\s*({escaped})(?:\s+|$)')

def extract_prefix(t, custom_regex_1=None, custom_regex_2=None, custom_regex_3=None):
    t = t.replace('[점검]', '').strip()
    m = re.match(r'^\s*(<?\[?(?:붙임|별첨|부록)\s*\d*\]?>?)', t)
    if m: return m.group(1).replace('<', '').replace('>', '').replace('[', '').replace(']', '').replace(' ', '')
    
    if custom_regex_1:
        m = custom_regex_1.match(t)
        if m: return re.sub(r'\s+', '', m.group(1))
    if custom_regex_2:
        m = custom_regex_2.match(t)
        if m: return re.sub(r'\s+', '', m.group(1))
    if custom_regex_3:
        m = custom_regex_3.match(t)
        if m: return re.sub(r'\s+', '', m.group(1))
        
    m = re.match(rf'^\s*(제\s*\d+\s*[장절]|[1-9]\d*(?:\.\d+)+|[{KOR_IDX}][-\.]\d+|[1-9]\d*(?:-\d+)+|\([1-9]\d*\)|\([{KOR_IDX}]\)|[{KOR_IDX}][\.\)）]|[1-9]\d*[\.\)）]|[A-Z][\.\)]|[1-9]\d*(?=\s+[가-힣a-zA-Z]))', t)
    if m: return re.sub(r'\s+', '', m.group(1))
    return None

def is_ghost_title(clean_t):
    clean_t = clean_t.lower()
    if '영문목차' in clean_t: return True
    if '영문요약서' in clean_t: return True
    for g in ['제출문', '별도제출물', '요약서', '요약문', '표지', '목차', '참고문헌']:
        if g in clean_t and len(clean_t) <= len(g) + 8: return True
        if g == '요약문' and '요약문' in clean_t: return True
    for g in ['summary', 'contents', 'content']:
        if g in clean_t and len(clean_t) <= len(g) + 5 and not re.search(r'[가-힣]', clean_t): return True
    return False

def is_restricted_1depth(clean_title):
    if not clean_title: return False
    clean_title = clean_title.lower()
    if '영문목차' in clean_title: return True
    if '영문요약서' in clean_title: return True
    for g in ['표지', '제출문', '별도제출물', '요약서', '요약문', '목차', '참고문헌']:
        if g in clean_title and len(clean_title) <= len(g) + 12: return True
        if g == '요약문' and '요약문' in clean_title: return True
    for g in ['summary', 'contents', 'content']:
        if g in clean_title and len(clean_title) <= len(g) + 5 and not re.search(r'[가-힣]', clean_title): return True
    if re.match(r'^\d*(붙임|별첨|부록)', clean_title): return True
    return False

def is_3depth_in_jang(title):
    t_no = re.sub(r'\s+', '', title)
    if re.match(r'^[1-9]\d*[\.\)]', t_no) or re.match(rf'^[{KOR_IDX}][\.\)]', t_no) or re.match(r'^[A-Z][\.\)]', t_no) or re.match(r'^\([1-9]\d*\)', t_no) or re.match(rf'^\([{KOR_IDX}]\)', t_no): return True
    return False

def find_anchor_in_page(toc_title, cache, p_idx, toc_end_idx=-1, custom_regex_1=None, custom_regex_2=None, custom_regex_3=None):
    if p_idx <= toc_end_idx: return None, 0.0, 0, 0 
    dict_data = cache.get_dict(p_idx)
    toc_body = PREFIX_STRIP_PATTERN.sub('', toc_title).strip()
    toc_clean = CLEAN_PATTERN.sub('', toc_body)
    if not toc_clean: toc_clean = CLEAN_PATTERN.sub('', toc_title)
    
    core_length = max(5, int(len(toc_clean) * 0.6))
    toc_core = toc_clean[:core_length]
    toc_prefix = extract_prefix(toc_title, custom_regex_1, custom_regex_2, custom_regex_3)
    
    for b in dict_data.get("blocks", []):
        if b.get("type") != 0: continue
        for l in b.get("lines", []):
            text, last_x1, max_size, main_flags, main_color = "", -1, 0.0, 0, 0
            for s in l.get("spans", []):
                span_text, s_x0 = s.get("text", ""), s["bbox"][0]
                if last_x1 != -1 and s_x0 - last_x1 > 3.0 and not text.endswith(' ') and not span_text.startswith(' '): text += " "
                text += span_text
                last_x1 = s["bbox"][2]
                if s.get("size", 0.0) > max_size: 
                    max_size = s.get("size", 0.0)
                    main_flags = s.get("flags", 0)
                    main_color = s.get("color", 0)
            
            text = fix_broken_characters(text.strip())
            text_prefix = extract_prefix(text, custom_regex_1, custom_regex_2, custom_regex_3)
            if toc_prefix and text_prefix and toc_prefix != text_prefix: continue

            text_body = PREFIX_STRIP_PATTERN.sub('', text).strip()
            text_clean = CLEAN_PATTERN.sub('', text_body)
            if not text_clean: text_clean = CLEAN_PATTERN.sub('', text)
            
            if toc_core in text_clean and len(text_clean) <= len(toc_clean) + 15: return l["bbox"][1], max_size, main_flags, main_color
            if len(toc_clean) - 5 <= len(text_clean) <= len(toc_clean) + 20:
                if get_ratio(toc_clean, text_clean[:len(toc_clean) + 5]) >= 0.75: return l["bbox"][1], max_size, main_flags, main_color
                    
    for b in dict_data.get("blocks", []):
        if b.get("type") != 0: continue
        block_text, min_y0, max_size, main_flags, main_color = "", 9999.0, 0.0, 0, 0
        for l in b.get("lines", []):
            if l["bbox"][1] < min_y0: min_y0 = l["bbox"][1]
            for s in l.get("spans", []):
                block_text += s.get("text", "")
                if s.get("size", 0.0) > max_size: 
                    max_size = s.get("size", 0.0)
                    main_flags = s.get("flags", 0)
                    main_color = s.get("color", 0)
        
        block_text = fix_broken_characters(block_text.strip())
        b_prefix = extract_prefix(block_text, custom_regex_1, custom_regex_2, custom_regex_3)
        if toc_prefix and b_prefix and toc_prefix != b_prefix: continue

        block_body = PREFIX_STRIP_PATTERN.sub('', block_text).strip()
        block_clean = CLEAN_PATTERN.sub('', block_body)
        if not block_clean: block_clean = CLEAN_PATTERN.sub('', block_text)
        if block_clean.find(toc_core) != -1 and block_clean.find(toc_core) < 50: return min_y0, max_size, main_flags, main_color
            
    return None, 0.0, 0, 0

def determine_level(title, has_jang, font_size=0.0, font_trackers=None, is_body_scan=False, custom_regex_1=None, custom_regex_2=None, custom_regex_3=None):
    t = title.strip()
    clean_t = CLEAN_PATTERN.sub('', t)
    
    if is_ghost_title(clean_t): return 1
    
    if custom_regex_1 and custom_regex_1.match(t): return 1
    if custom_regex_2 and custom_regex_2.match(t): return 2
    if custom_regex_3 and custom_regex_3.match(t): return 3
    
    if re.match(r'^제\s*\d+\s*장', t) or re.match(r'^<?\[?(붙임|별첨|부록)', t): return 1
    
    if has_jang:
        if re.match(r'^제\s*\d+\s*절', t): return 2
        if is_3depth_in_jang(t): return 3
        return 99 
        
    if re.match(r'^[1-9]\d*\.\d+\.\d+', t) or re.match(r'^[1-9]\d*-\d+-\d+[\.\)]?', t) or re.match(rf'^[{KOR_IDX}]-\d+-\d+[\.\)]?', t): return 3
    if re.match(r'^\([1-9]\d*\)(?:\s+|$)', t) or re.match(rf'^\([{KOR_IDX}]\)(?:\s+|$)', t) or re.match(r'^[a-z]\)(?:\s+|$)', t): return 3

    if re.match(r'^제\s*\d+\s*절', t): return 2
    if re.match(r'^[1-9]\d*\.\d+[\.\s]?', t): return 2 
    if re.match(r'^[1-9]\d*-\d+[\.\)]?', t): return 2 
    if re.match(r'^[A-Za-z][\.\)]\s*', t): return 2 
    if re.match(r'^[1-9]\d*[\)）](?:\s+|$)', t): return 2
    if re.match(rf'^[{KOR_IDX}][\.\)）]\s*', t): return 2 
    
    if re.match(r'^[1-9]\d*\.(?:\s+|$)', t) or re.match(r'^[1-9]\d*\s+[가-힣a-zA-Z]', t):
        if font_size > 0.0 and font_trackers is not None:
            if font_trackers.get('depth1', 0.0) == 0.0: font_trackers['depth1'] = font_size
            elif font_size <= font_trackers['depth1'] - 0.8: return 2
        return 1
        
    return 2

def get_seq_info(title):
    t = title.strip()
    m = re.match(r'^([1-9]\d*(?:\.\d+)+)\.(\d+)[\.\)]?(?:\s+|$)', t)
    if m: return (f"num_dot_sub_{m.group(1).replace('.', '_')}", int(m.group(2)))
    m = re.match(r'^([1-9]\d*)\.(\d+)[\.\)]?(?:\s+|$)', t)
    if m: return (f"num_dot_{m.group(1)}", int(m.group(2)))
    m = re.match(r'^([1-9]\d*(?:-\d+)*)-([1-9]\d*)[\.\)]?(?:\s+|$)', t)
    if m: return (f"num_dash_sub_{m.group(1).replace('-', '_')}", int(m.group(2)))
    m = re.match(r'^제?\s*([1-9]\d*)\s*장(?:\s+|$)', t)
    if m: return ('num_jang', int(m.group(1)))
    m = re.match(r'^제?\s*([1-9]\d*)\s*절(?:\s+|$)', t)
    if m: return ('num_jeol', int(m.group(1)))
    m = re.match(r'^\(\s*([1-9]\d*)\s*\)(?:\s+|$)', t)
    if m: return ('num_paren_both', int(m.group(1)))
    m = re.match(r'^([1-9]\d*)\s*[\)）](?:\s+|$)', t)
    if m: return ('num_paren_right', int(m.group(1)))
    m = re.match(rf'^([{KOR_IDX}])\s*\.(?:\s*|$)', t)
    if m: return ('kor_dot', KOR_MAP.get(m.group(1)))
    m = re.match(rf'^([{KOR_IDX}])\s*[\)）](?:\s*|$)', t)
    if m: return ('kor_paren_right', KOR_MAP.get(m.group(1)))
    m = re.match(rf'^\(\s*([{KOR_IDX}])\s*\)(?:\s+|$)', t)
    if m: return ('kor_paren_both', KOR_MAP.get(m.group(1)))
    m = re.match(r'^([1-9]\d*)\s*\.(?:\s*|$)', t)
    if m: return ('num_dot', int(m.group(1)))
    m = re.match(r'^([A-Za-z])[\.\)](?:\s+|$)', t)
    if m: return ('alpha_dot', ord(m.group(1).upper()) - 64)
    return (None, None)

def make_prefix(seq_type, num):
    if not num: return None
    if seq_type.startswith('num_dot_sub_'): return f"{seq_type[12:].replace('_', '.')}.{num}"
    if seq_type.startswith('num_dot_'): return f"{seq_type[8:]}.{num}"
    if seq_type.startswith('num_dash_sub_'): return f"{seq_type[13:].replace('_', '-')}-{num}"
    if seq_type == 'alpha_dot': return f"{chr(num + 64)}." 
    if num > len(KOR_CHARS): return None
    if seq_type == 'num_jeol': return f"제{num}절"
    if seq_type == 'num_paren_both': return f"({num})"
    if seq_type == 'num_paren_right': return f"{num})"
    if seq_type == 'kor_dot': return f"{KOR_CHARS[num-1]}."
    if seq_type == 'kor_paren_right': return f"{KOR_CHARS[num-1]})"
    if seq_type == 'kor_paren_both': return f"({KOR_CHARS[num-1]})"
    if seq_type == 'num_dot': return f"{num}."
    return None

def get_parent_1depth(p_idx, y0, items):
    for item in reversed(items):
        if item['level'] == 1:
            if item['page_idx'] < p_idx or (item['page_idx'] == p_idx and item['y0'] <= y0 + 10.0):
                return CLEAN_PATTERN.sub('', item['title'].replace('[점검] ', '')) or str(item['toc_idx'])
    return None

def get_sort_key(x):
    y_val = x['y0'] if x['y0'] > 0.0 else -1.0
    t_val = x['toc_idx'] if x.get('toc_idx', 999) != 999 else 9999
    return (x['page_idx'], y_val, t_val)

# ==========================================
# 통합 프로세스 로직 
# ==========================================
def process_pdf_bookmarks(input_path, output_path, scan_mode, exclude_footnotes, max_depth, custom_lvl1, custom_lvl2, custom_lvl3, st_logger):
    
    MAX_DEPTH = max_depth
    SCAN_MODE = scan_mode
    
    rx_lvl1 = parse_custom_format(custom_lvl1)
    rx_lvl2 = parse_custom_format(custom_lvl2)
    rx_lvl3 = parse_custom_format(custom_lvl3)
    
    with fitz.open(input_path) as doc:
        total_pages = len(doc)
        st_logger.print(f"-> 총 {total_pages}페이지 확인됨. 최대 추출 깊이: {MAX_DEPTH}-depth 적용")
        
        cache = PageCache(doc, exclude_footnotes)

        st_logger.print("1. 국문 목차 페이지 전용 탐색 중...")
        toc_text, toc_page_idx = "", -1
        
        for i in range(min(30, total_pages)):
            blocks = sorted(cache.get_blocks(i), key=lambda b: b[1])
            is_eng, is_kor = False, False
            for b in blocks[:20]:
                text_upper = b[4].strip().upper()
                clean_text = CLEAN_PATTERN.sub('', text_upper)
                if not clean_text: continue
                if "CONTENTS" in text_upper or "영문목차" in clean_text: is_eng = True
                if clean_text in ["목차", "차례", "contents"] or re.search(r'<\s*목\s*차\s*>', text_upper): is_kor = True
            if is_eng: continue
            if is_kor:
                toc_page_idx = i
                st_logger.print(f"  -> {i + 1}p에서 국문 목차를 성공적으로 찾았습니다.")
                break

        if toc_page_idx == -1:
            st_logger.print("국문 목차를 찾을 수 없어 종료합니다.")
            return None
            
        toc_end_idx = toc_page_idx
        for i in range(toc_page_idx, min(toc_page_idx + 8, total_pages)):
            page_text = cache.get_text(i)
            if i > toc_page_idx:
                header_text = page_text[:200].upper()
                if "CONTENTS" in header_text or "영문목차" in CLEAN_PATTERN.sub('', header_text): break 
            if i == toc_page_idx or len(re.findall(r'[\.·]{3,}', page_text)) >= 2 or re.search(r'<\s*목\s*차\s*>', page_text):
                toc_text += page_text + "\n"
                toc_end_idx = i 
            else: break

        toc_text = re.sub(r'([1-9]\d*-)\s*\n\s*([1-9]\d*)', r'\1\2', toc_text)
        toc_text = re.sub(r'([1-9]\d*[\.\)]|[{KOR_IDX}][\.\)])\s*\n\s*([가-힣a-zA-Z<\[])', r'\1 \2', toc_text)
        toc_text = re.sub(r'(제\s*\d+)\s*\n+\s*(장|절)', r'\1\2', toc_text)
        toc_text = re.sub(r'(제\s*\d+\s*[장절])\s*\n+\s*([가-힣a-zA-Z<\[])', r'\1 \2', toc_text)
        # [수정] 1페이지 유령항목 찢어짐 방지 정규식
        toc_text = re.sub(r'([가-힣a-zA-Z\,])\s*\n\s*(?!(?:(?:별\s*도\s*)?제\s*출\s*(?:문|물)|보\s*고\s*서|요\s*약|목\s*차|표\s*지|참\s*고\s*문\s*헌|Summary|Contents))([가-힣a-zA-Z\(\<\[])', r'\1 \2', toc_text, flags=re.IGNORECASE)
        toc_text = re.sub(r'([가-힣a-zA-Z\>\]\)])\s*\n+\s*(?:\||[\.·_-]{2,})?\s*(\d+)(?=\s*(\n|$))', r'\1 | \2', toc_text)

        raw_items, parsed_titles = [], set()
        for match in TOC_PATTERN.finditer(toc_text):
            title = fix_broken_characters(re.sub(r'^[\s]+', '', match.group(1).strip()).replace("목차", "").strip())
            title = re.sub(r'[\.·\-_]{3,}.*$', '', title).strip() 
            if "저자소개" in CLEAN_PATTERN.sub('', title): continue
            title = re.sub(r'^[^a-zA-Z0-9가-힣<\[\(]+', '', title).strip()
            if len(CLEAN_PATTERN.sub('', title)) > 2 and re.search(r'[가-힣a-zA-Z]', title):
                raw_items.append({'title': title, 'p_num': int(match.group(2))})
                parsed_titles.add(CLEAN_PATTERN.sub('', title))

        for line in toc_text.split('\n'):
            line = line.strip()
            if not line: continue
            line = re.sub(r'[\.·\-_]{3,}.*$', '', line).strip()
            clean_line = CLEAN_PATTERN.sub('', line)
            if not clean_line or clean_line in parsed_titles: continue
            is_dup = False
            for pt in parsed_titles:
                if len(pt) > 5 and len(clean_line) > 5 and (pt in clean_line or clean_line in pt):
                    is_dup = True; break
            if is_dup: continue
            if CANDIDATE_PATTERN.match(line):
                title = fix_broken_characters(line.replace("목차", "").strip())
                if "저자소개" in CLEAN_PATTERN.sub('', title): continue
                title = re.sub(r'^[^a-zA-Z0-9가-힣<\[\(]+', '', title).strip()
                if len(CLEAN_PATTERN.sub('', title)) > 2 and re.search(r'[가-힣a-zA-Z]', title):
                    raw_items.append({'title': title, 'p_num': 0})
                    parsed_titles.add(CLEAN_PATTERN.sub('', title))

        has_jang = any(re.match(r'^제\s*\d+\s*장', re.sub(r'\s+', '', t['title'])) for t in raw_items)
        if not has_jang and re.search(r'제\s*\d+\s*장', re.sub(r'\s+', '', toc_text)): has_jang = True
        has_korean_toc = any(re.search(r'[가-힣]', t['title']) for t in raw_items)
        
        toc_bookmarks = []
        for t_dict in raw_items:
            title = t_dict['title']
            if has_korean_toc:
                clean_t = CLEAN_PATTERN.sub('', title).lower()
                if any(x in clean_t for x in ["표목차", "그림목차", "영문목차"]): continue
                title_body = PREFIX_STRIP_PATTERN.sub('', title).strip()
                if not re.search(r'[가-힣]', title_body) and not re.match(r'^<?\[?(붙임|별첨|부록)', title): continue
            
            if has_jang:
                is_jang = bool(re.match(r'^제\d+장', re.sub(r'\s+', '', title)))
                is_jeol = bool(re.match(r'^제\d+절', re.sub(r'\s+', '', title)))
                is_butim = bool(re.match(r'^<?\[?(붙임|별첨|부록)', title))
                is_ghost = is_ghost_title(CLEAN_PATTERN.sub('', title))
                is_valid = is_jang or is_jeol or is_butim or is_ghost or is_3depth_in_jang(title)
                if not is_valid: continue
            toc_bookmarks.append(t_dict)

        st_logger.print("\n2. 본문 좌표 추적 및 1-2-3 depth 상하 범주 유효성 통제 중...")
        offset = 0
        for item in toc_bookmarks:
            if item['p_num'] == 0: continue
            for p_idx in range(toc_end_idx + 1, total_pages):
                y0, _, _, _ = find_anchor_in_page(item['title'], cache, p_idx, toc_end_idx, custom_regex_1=rx_lvl1, custom_regex_2=rx_lvl2, custom_regex_3=rx_lvl3)
                if y0 is not None:
                    offset = p_idx - item['p_num']
                    break
            if offset != 0: break

        resolved_items = []
        created_titles = set()
        last_success_page_idx, seq_page, seq_y0 = toc_end_idx + 1, toc_end_idx + 1, 0.0
        last_1depth_coord, last_2depth_coord = (-1, -1), (-1, -1)

        for toc_idx, toc_item in enumerate(toc_bookmarks):
            title = toc_item['title']
            printed_page = toc_item['p_num']
            clean_t = CLEAN_PATTERN.sub('', title)
            if clean_t in created_titles: continue

            level = determine_level(title, has_jang, font_size=0, is_body_scan=False, custom_regex_1=rx_lvl1, custom_regex_2=rx_lvl2, custom_regex_3=rx_lvl3)
            expected_page = printed_page + offset if printed_page > 0 else seq_page
            target_page_idx = min(max(expected_page, toc_end_idx + 1), total_pages - 1)
            found, found_page, found_y0, found_f_size, found_flags, found_color = False, target_page_idx, 0.0, 0.0, 0, 0

            min_page, min_y0 = -1, -1
            if level == 3 and last_2depth_coord[0] != -1: min_page, min_y0 = last_2depth_coord
            elif level in [2, 3] and last_1depth_coord[0] != -1: min_page, min_y0 = last_1depth_coord
            strict_seq_page, strict_seq_y0 = seq_page, seq_y0

            for local_offset in [0, -1, 1, -2, 2]:
                check_idx = target_page_idx + local_offset
                if toc_end_idx < check_idx < total_pages: 
                    y0, f_size, f_flags, f_color = find_anchor_in_page(title, cache, check_idx, toc_end_idx, custom_regex_1=rx_lvl1, custom_regex_2=rx_lvl2, custom_regex_3=rx_lvl3)
                    if y0 is not None:
                        if min_page != -1 and (check_idx < min_page or (check_idx == min_page and y0 < min_y0 - 5.0)): continue
                        if check_idx < strict_seq_page or (check_idx == strict_seq_page and y0 < strict_seq_y0 - 5.0): continue
                        found, found_page, found_y0, found_f_size, found_flags, found_color = True, check_idx, y0, f_size, f_flags, f_color
                        break
                        
            if not found:
                search_limit = min(total_pages, target_page_idx + 15)
                for check_idx in range(last_success_page_idx, search_limit):
                    y0, f_size, f_flags, f_color = find_anchor_in_page(title, cache, check_idx, toc_end_idx, custom_regex_1=rx_lvl1, custom_regex_2=rx_lvl2, custom_regex_3=rx_lvl3)
                    if y0 is not None:
                        if min_page != -1 and (check_idx < min_page or (check_idx == min_page and y0 < min_y0 - 5.0)): continue
                        if check_idx < strict_seq_page or (check_idx == strict_seq_page and y0 < strict_seq_y0 - 5.0): continue
                        found, found_page, found_y0, found_f_size, found_flags, found_color = True, check_idx, y0, f_size, f_flags, f_color
                        break
            
            if found: 
                last_success_page_idx, seq_page, seq_y0 = found_page, found_page, found_y0
                if level == 1: last_1depth_coord, last_2depth_coord = (found_page, found_y0), (-1, -1)
                elif level == 2: last_2depth_coord = (found_page, found_y0)
            else:
                found_page = max(toc_end_idx + 1, printed_page + offset) if printed_page > 0 else seq_page
                found_y0 = 0.0
                seq_page, seq_y0 = found_page, 0.0
                if level == 1: last_1depth_coord = (found_page, 0.0)
                elif level == 2: last_2depth_coord = (found_page, 0.0)
            
            final_level = determine_level(title, has_jang, font_size=found_f_size, is_body_scan=False, custom_regex_1=rx_lvl1, custom_regex_2=rx_lvl2, custom_regex_3=rx_lvl3) if found else level
            resolved_items.append({
                'toc_idx': toc_idx, 'title': title if found else f"[점검] {title}", 
                'page_idx': found_page, 'y0': found_y0, 'f_size': found_f_size, 
                'flags': found_flags, 'color': found_color,
                'level': final_level, 'is_failed': not found, 'body_matched': found, 'printed_page': printed_page
            })
            created_titles.add(clean_t)

        global_font_trackers = {'depth1': 0.0}

        st_logger.print("\n3. 본문 스캔(FULL_SCAN) 및 폰트/플래그 프로파일링 중...")
        # [수정] 1페이지 유령항목 포착을 위해 스캔 범위를 첫 페이지부터 적용
        for p_idx in range(total_pages):
            if toc_page_idx != -1 and toc_page_idx <= p_idx <= toc_end_idx:
                continue
                
            for line in cache.get_valid_lines(p_idx):
                text, y0, max_size, main_flags, main_color, is_desc = line['text'], line['y0'], line['max_size'], line['flags'], line['color'], line['is_desc']
                
                if re.match(r'^\s*<*(표|그림|Table|Fig)[\.\s]*\d+', text, re.IGNORECASE): continue
                
                text_nospace = text.replace(" ", "")
                is_special_kws_match = all(k in text_nospace for k in ["붙임", "연구책임자", "대표", "연구실적"])
                
                if is_special_kws_match:
                    mapped = False
                    for item in resolved_items:
                        item_nospace = item['title'].replace('[점검] ', '').replace(" ", "")
                        if all(k in item_nospace for k in ["붙임", "연구책임자", "대표", "연구실적"]):
                            if item.get('is_failed', True):
                                item.update({'title': text, 'page_idx': p_idx, 'y0': y0, 'f_size': max_size, 'flags': main_flags, 'color': main_color, 'is_failed': False, 'body_matched': True, 'level': 1})
                                if '[점검]' in item['title']: item['title'] = item['title'].replace('[점검] ', '')
                            mapped = True
                            break
                    if not mapped:
                        resolved_items.append({'toc_idx': 999, 'title': text, 'page_idx': p_idx, 'y0': y0, 'f_size': max_size, 'flags': main_flags, 'color': main_color, 'level': 1, 'is_failed': False, 'body_matched': True, 'printed_page': 0})
                    continue 

                if CANDIDATE_PATTERN.match(text) or (rx_lvl1 and rx_lvl1.match(text)) or (rx_lvl2 and rx_lvl2.match(text)) or (rx_lvl3 and rx_lvl3.match(text)):
                    if not re.search(r'[가-힣a-zA-Z]', text): continue
                    
                    prefix_str = extract_prefix(text, rx_lvl1, rx_lvl2, rx_lvl3)
                    if prefix_str:
                        rest_text = text[text.find(prefix_str) + len(prefix_str):].lstrip()
                        if re.match(r'^(?:%|%p|배|초|원|건|명|개|단계|년|월|일|회|종)(?:\s+|[^\w]|$)', rest_text): continue
                            
                    if any(fs in text for fs in ["이 보고서는", "발표하는 때에는", "국가과학기술기밀"]): continue
                    
                    cand_prefix, cand_clean, is_dup = extract_prefix(text, rx_lvl1, rx_lvl2, rx_lvl3), CLEAN_PATTERN.sub('', text), False
                    cand_level_toc = determine_level(text, has_jang, font_size=max_size, font_trackers=global_font_trackers, is_body_scan=True, custom_regex_1=rx_lvl1, custom_regex_2=rx_lvl2, custom_regex_3=rx_lvl3)
                    if cand_level_toc == 99: continue
                    
                    cand_1depth_parent = get_parent_1depth(p_idx, y0, resolved_items)

                    if cand_1depth_parent and is_restricted_1depth(cand_1depth_parent):
                        if cand_level_toc in [2, 3]: continue
                        if cand_level_toc == 1 and not (is_ghost_title(cand_clean) or re.match(r'^<?\[?(붙임|별첨|부록)', text.strip()) or re.match(r'^제\s*\d+\s*[장절]', text.strip())): continue
                    
                    for item in resolved_items:
                        if item['page_idx'] == p_idx and abs(item['y0'] - y0) < 5.0:
                            item_prefix = extract_prefix(item['title'].replace('[점검] ', ''), rx_lvl1, rx_lvl2, rx_lvl3)
                            if cand_prefix and item_prefix and cand_prefix != item_prefix: continue 
                            item['is_failed'], item['body_matched'] = False, True
                            if '점검' in item['title']: item['title'] = item['title'].replace('[점검] ', '')
                            is_dup = True; break
                                
                    if not is_dup and cand_prefix:
                        for item in resolved_items:
                            if item['level'] != cand_level_toc: continue 
                            if cand_level_toc in [2, 3] and get_parent_1depth(item['page_idx'], item['y0'], resolved_items) != cand_1depth_parent: continue 
                            item_prefix = extract_prefix(item['title'].replace('[점검] ', ''), rx_lvl1, rx_lvl2, rx_lvl3)
                            if item_prefix == cand_prefix and get_ratio(CLEAN_PATTERN.sub('', item['title'].replace('[점검] ', '')), cand_clean) > 0.40:
                                item.update({'title': text, 'page_idx': p_idx, 'y0': y0, 'f_size': max_size, 'flags': main_flags, 'color': main_color, 'is_failed': False, 'body_matched': True})
                                if '점검' in item['title']: item['title'] = item['title'].replace('[점검] ', '')
                                is_dup = True; break
                                    
                    if not is_dup:
                        for x in resolved_items:
                            if x['level'] == cand_level_toc and CLEAN_PATTERN.sub('', x['title'].replace('[점검] ', '')) == cand_clean:
                                if cand_level_toc in [2, 3] and get_parent_1depth(x['page_idx'], x['y0'], resolved_items) != cand_1depth_parent: continue
                                is_dup = True; break

                    if not is_dup:
                        if SCAN_MODE == "FULL_SCAN":
                            is_garbage = False
                            if re.search(r'(습니다|입니다|합니다|됩니다|한다|된다|이다|있다|없다|같다|기대된다|판단된다|보인다|하였다|되었다|진행함|확인함|관찰함|측정함|평가함|도출함|사용함|나타남|수행함|제조함|분석함|계산함)\.\s+[가-힣A-Z]', text): 
                                is_garbage = True
                            if len(text) < 100 and not text.endswith(('.', '다.', '함.', '음.', '임.')):
                                if ':' in text and len(text.split(':', 1)[1]) > 15: is_garbage = True
                                if '：' in text and len(text.split('：', 1)[1]) > 15: is_garbage = True
                                if re.search(r'(을|를|는|으로|에서|부터|까지|에게|통해|대해|위해|관해|따른|인한|하는|있는|인|및|또는)\s*$', text): is_garbage = True
                                if len(text) >= 20 and re.search(r'(의|로|과|와|할|한|된|될)\s*$', text):
                                    if not re.search(r'(결과|효과|성과|교과|경로|회로|역할|총괄|분할|개요|필요성|중요성|목표|현황)\s*$', text): 
                                        is_garbage = True
                            
                            if is_garbage: continue

                        resolved_items.append({'toc_idx': 999, 'title': text, 'page_idx': p_idx, 'y0': y0, 'f_size': max_size, 'flags': main_flags, 'color': main_color, 'level': cand_level_toc, 'is_failed': False, 'body_matched': True, 'printed_page': 0})

        resolved_items.sort(key=get_sort_key)

        st_logger.print("\n4-A. [최종 방어선] 1-depth, 2-depth 시퀀스/페이지 역전 검증 및 영구 잠금 중...")
        strict_items_1_2 = []
        
        current_1d_title = None
        current_2d_title = None
        
        current_seq_state = {1: 0, 2: 0}
        current_seq_type = {1: None, 2: None}
        current_font_profile = {2: None} 
        
        is_current_1d_failed = False
        
        depth1_type = None
        depth1_last_num = 0
        depth1_last_page = -1

        for item in resolved_items:
            lvl = item['level']
            if lvl not in [1, 2, 99]: continue 
            
            title = item['title']
            clean_t = CLEAN_PATTERN.sub('', title).lower()
            
            if is_ghost_title(clean_t) or title in ['표지', '목차', '참고문헌']:
                strict_items_1_2.append(item)
                if lvl == 1: 
                    current_1d_title = title
                    is_current_1d_failed = '[점검]' in title
                    current_seq_state = {1: 0, 2: 0}
                    current_seq_type = {1: None, 2: None}
                    current_font_profile = {2: None}
                    depth1_type = None; depth1_last_num = 0; depth1_last_page = -1
                continue
                
            st_type, sn = get_seq_info(title.replace('[점검] ', ''))
            
            if lvl == 1:
                is_valid_1depth = True
                if st_type and sn is not None:
                    if depth1_type is None:
                        depth1_type = st_type
                        depth1_last_num = sn
                        depth1_last_page = item['page_idx']
                    else:
                        if st_type == depth1_type:
                            if sn > depth1_last_num and item['page_idx'] >= depth1_last_page:
                                depth1_last_num = sn
                                depth1_last_page = item['page_idx']
                            elif sn <= depth1_last_num or item['page_idx'] < depth1_last_page:
                                is_valid_1depth = False
                                st_logger.print(f"  -> [경고] 1-depth 순서/페이지 역전 감지됨: '{title}' (배제 처리)")
                        else:
                            depth1_type = st_type
                            depth1_last_num = sn
                            depth1_last_page = item['page_idx']

                if is_valid_1depth:
                    current_1d_title = title
                    current_2d_title = None 
                    is_current_1d_failed = '[점검]' in title
                    current_seq_state = {1: 0, 2: 0}
                    current_seq_type = {1: None, 2: None}
                    current_font_profile = {2: None}
                    strict_items_1_2.append(item)
                else:
                    continue
                
            elif lvl == 2:
                if is_current_1d_failed: continue 
                if not current_1d_title: continue

                is_jump_error = False
                skip_item = False
                item_profile = (round(item.get('f_size', 0.0), 1), item.get('flags', 0), item.get('color', 0))
                
                if sn is not None and st_type is not None:
                    if current_seq_type[lvl] is None:
                        if sn > 1: is_jump_error = True
                        current_seq_type[lvl] = st_type
                        current_seq_state[lvl] = sn
                        current_font_profile[lvl] = item_profile
                    else:
                        if st_type != current_seq_type[lvl]: skip_item = True
                        elif sn <= current_seq_state[lvl]: skip_item = True
                        elif sn > current_seq_state[lvl] + 1: skip_item = True
                        else:
                            base_profile = current_font_profile[lvl]
                            if base_profile:
                                b_size, b_flags, b_color = base_profile
                                i_size, i_flags, i_color = item_profile
                                if abs(b_size - i_size) > 1.0 or b_flags != i_flags or b_color != i_color:
                                    skip_item = True
                                    
                        if not skip_item and not is_jump_error:
                            current_seq_state[lvl] = sn
                else:
                    skip_item = True

                if skip_item: continue 
                            
                if is_jump_error:
                    if not item['title'].startswith('[점검]'):
                        item['title'] = "[점검] " + item['title']
                
                strict_items_1_2.append(item)

        strict_items_3 = []
        if MAX_DEPTH >= 3:
            st_logger.print("\n4-B. [독립 스캔] 3-depth 시퀀스 유효성 검증 중 (1, 2-depth 보존)...")
            
            merged_for_pass2 = strict_items_1_2 + [i for i in resolved_items if i['level'] == 3]
            merged_for_pass2.sort(key=get_sort_key)
            
            current_2d_valid = False
            current_seq_state_3 = 0
            current_seq_type_3 = None
            current_font_profile_3 = None
            
            for item in merged_for_pass2:
                lvl = item['level']
                if lvl == 1:
                    current_2d_valid = False
                    current_seq_state_3 = 0
                    current_seq_type_3 = None
                    current_font_profile_3 = None
                elif lvl == 2:
                    current_2d_valid = True
                    current_seq_state_3 = 0
                    current_seq_type_3 = None
                    current_font_profile_3 = None
                elif lvl == 3:
                    if not current_2d_valid: continue 
                    
                    st_type, sn = get_seq_info(item['title'].replace('[점검] ', ''))
                    is_jump_error = False
                    skip_item = False
                    item_profile = (round(item.get('f_size', 0.0), 1), item.get('flags', 0), item.get('color', 0))
                    
                    if sn is not None and st_type is not None:
                        if current_seq_type_3 is None:
                            if sn > 1: is_jump_error = True
                            current_seq_type_3 = st_type
                            current_seq_state_3 = sn
                            current_font_profile_3 = item_profile
                        else:
                            if st_type != current_seq_type_3: skip_item = True
                            elif sn <= current_seq_state_3: skip_item = True
                            elif sn > current_seq_state_3 + 1: skip_item = True
                            else:
                                base_profile = current_font_profile_3
                                if base_profile:
                                    b_size, b_flags, b_color = base_profile
                                    i_size, i_flags, i_color = item_profile
                                    if abs(b_size - i_size) > 1.0 or b_flags != i_flags or b_color != i_color:
                                        skip_item = True
                            if not skip_item and not is_jump_error:
                                current_seq_state_3 = sn
                    else:
                        skip_item = True
                        
                    if skip_item: continue
                    
                    if is_jump_error:
                        if not item['title'].startswith('[점검]'):
                            item['title'] = "[점검] " + item['title']
                            
                    strict_items_3.append(item)
                    
        resolved_items = strict_items_1_2 + strict_items_3
        resolved_items.sort(key=get_sort_key)

        st_logger.print("\n5. 요약문 등 유령항목 단일화 및 최종 책갈피 트리 구성 중...")
        filtered_items, seen_ghosts = [], set()
        
        for item in resolved_items:
            clean_title = CLEAN_PATTERN.sub('', item['title']).lower()
            raw_title = item['title'].replace('[점검] ', '').strip()
            ghost_key = None
            
            if '영문목차' in clean_title: continue
            
            if not re.match(r'^<?\[?(붙임|별첨|부록|제\s*\d+\s*[장절])', raw_title):
                if '영문요약서' in clean_title or ('summary' in clean_title and not re.search(r'[가-힣]', clean_title)):
                    ghost_key = 'Summary'
                elif ('contents' in clean_title or 'content' in clean_title) and not re.search(r'[가-힣]', clean_title):
                    ghost_key = 'Contents'
                else:
                    # [수정] 단일화 로직 추가: <별도 제출물>, 제 출 문 등을 '제출문'으로 통일
                    for g in ['제출문', '별도제출물', '요약서', '요약문', '참고문헌']:
                        if g in clean_title:
                            if g == '별도제출물':
                                ghost_key = '제출문'
                                break
                            if g == '요약문' and '요약문' in clean_title: ghost_key = g; break
                            if len(clean_title) <= len(g) + 12: ghost_key = g; break
                    
            if ghost_key:
                if ghost_key in seen_ghosts: continue  
                seen_ghosts.add(ghost_key)
                
                if ghost_key == '참고문헌':
                    item['title'] = raw_title
                else:
                    item['title'] = ghost_key
                
                item['level'] = 1 
                filtered_items.append(item)
            elif any(x in clean_title for x in ['표지', '목차']) and len(clean_title) <= 10: continue 
            else: filtered_items.append(item)
                
        filtered_items.append({'toc_idx': -3, 'title': '표지', 'page_idx': 0, 'y0': 0.0, 'f_size': 0.0, 'level': 1, 'is_failed': False, 'body_matched': True})
        if toc_page_idx != -1: filtered_items.append({'toc_idx': -2, 'title': '목차', 'page_idx': toc_page_idx, 'y0': 0.0, 'f_size': 0.0, 'level': 1, 'is_failed': False, 'body_matched': True})
            
        resolved_items = sorted(filtered_items, key=get_sort_key)
        
        new_toc, prev_level, current_1depth_title = [], 0, ""
        for item in resolved_items:
            item['title'] = item['title'].replace('<', '').replace('>', '').strip()
            
            target_level = item['level']
            if target_level == 1: current_1depth_title = CLEAN_PATTERN.sub('', item['title']).lower()
            
            if item['title'] == '참고문헌':
                target_level = 2 if '기타' in current_1depth_title else 1 
                if target_level == 1: current_1depth_title = '참고문헌'
            
            if target_level > MAX_DEPTH: continue
            if target_level > 1 and any(x in current_1depth_title for x in ['표지', '제출문', '요약서', '요약문', '목차', '참고문헌', '붙임', '별첨', '부록']): continue
            if target_level > prev_level + 1: target_level = prev_level + 1
            
            y0_coord = max(0, item['y0'] - 20)
            dest_dict = {"kind": fitz.LINK_GOTO, "to": fitz.Point(0, y0_coord)}
            
            safe_page = min(item['page_idx'] + 1, total_pages)
            new_toc.append([target_level, item['title'], safe_page, dest_dict])
            prev_level = target_level
            
            indent = '    ' * (target_level - 1)
            st_logger.print(f"{indent}{item['title']} ({safe_page}p)")

        st_logger.print(f"끝페이지 ({total_pages}p)")
        new_toc.append([1, "끝페이지", total_pages, {"kind": fitz.LINK_GOTO, "to": fitz.Point(0, 0)}])
        
        doc.set_toc(new_toc)
        doc.save(output_path)

    st_logger.print("\n✨ 성공! 책갈피 생성이 완료되었습니다.")
    return new_toc


# ==========================================
# Streamlit 웹 UI 실행부
# ==========================================
st.set_page_config(page_title="PDF 책갈피 자동 생성기", layout="wide")

st.title("📑 PDF 연구보고서 책갈피 자동 생성기")
st.markdown("연구보고서 PDF 파일을 업로드하면 텍스트와 좌표를 분석하여 **자동으로 목차(책갈피)를 생성**합니다.")

st.sidebar.header("⚙️ 실행 옵션 설정")
SCAN_MODE = st.sidebar.selectbox("1. 스캔 모드", ["FULL_SCAN", "TOC_BASED", "ALL"], index=2)
TARGET_DEPTH = st.sidebar.number_input("2. 최대 추출 뎁스 (Depth)", min_value=1, max_value=5, value=2, step=1)
EXCLUDE_FOOTNOTES = st.sidebar.checkbox("3. 하단 각주(Footnote) 강제 배제", value=False)

st.sidebar.markdown("---")
st.sidebar.subheader("🎯 맞춤형 기호 강제 지정 (옵션)")
st.sidebar.caption("본문 폰트 차이로 판별이 꼬일 때 입력하세요.<br/>미입력 시 기본 자동 판별이 작동합니다.", unsafe_allow_html=True)
CUSTOM_LVL1 = st.sidebar.text_input("1-depth (대분류) 기호", value="", placeholder="예: 1.")
CUSTOM_LVL2 = st.sidebar.text_input("2-depth (중분류) 기호", value="", placeholder="예: 1-1.")
CUSTOM_LVL3 = st.sidebar.text_input("3-depth (소분류) 기호", value="", placeholder="예: 1)")

uploaded_file = st.file_uploader("PDF 파일을 선택하세요.", type=["pdf"])

if 'current_file' not in st.session_state:
    st.session_state.current_file = None
if 'scan_mode_run' not in st.session_state:
    st.session_state.scan_mode_run = None

if uploaded_file is not None:
    if st.session_state.current_file != uploaded_file.name:
        st.session_state.current_file = uploaded_file.name
        st.session_state.scan_mode_run = None
        for key in ['pdf_data_single', 'logs_single', 'pdf_data_full', 'logs_full', 'pdf_data_toc', 'logs_toc']:
            st.session_state.pop(key, None)

    if st.button("🚀 책갈피 생성 시작", type="primary"):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_in:
            tmp_in.write(uploaded_file.getvalue())
            tmp_in_path = tmp_in.name
            
        st.session_state.scan_mode_run = SCAN_MODE

        live_status_container = st.empty()
        with live_status_container.container():
            if SCAN_MODE == "ALL":
                tmp_out_full = tmp_in_path.replace(".pdf", "_full.pdf")
                tmp_out_toc = tmp_in_path.replace(".pdf", "_toc.pdf")
                
                col1, col2 = st.columns(2)
                col1.markdown("#### 🔍 FULL_SCAN 진행 현황")
                logger_full = StreamlitLogger(col1)
                col2.markdown("#### 🔍 TOC_BASED 진행 현황")
                logger_toc = StreamlitLogger(col2)
                
                with st.spinner("FULL_SCAN 모드로 분석 중..."):
                    toc_full = process_pdf_bookmarks(tmp_in_path, tmp_out_full, "FULL_SCAN", EXCLUDE_FOOTNOTES, TARGET_DEPTH, CUSTOM_LVL1, CUSTOM_LVL2, CUSTOM_LVL3, logger_full)
                
                with st.spinner("TOC_BASED 모드로 분석 중..."):
                    toc_toc = process_pdf_bookmarks(tmp_in_path, tmp_out_toc, "TOC_BASED", EXCLUDE_FOOTNOTES, TARGET_DEPTH, CUSTOM_LVL1, CUSTOM_LVL2, CUSTOM_LVL3, logger_toc)
                
                if toc_full and toc_toc:
                    st.session_state.logs_full = logger_full.logs
                    st.session_state.logs_toc = logger_toc.logs
                    with open(tmp_out_full, "rb") as f: st.session_state.pdf_data_full = f.read()
                    with open(tmp_out_toc, "rb") as f: st.session_state.pdf_data_toc = f.read()
                    
                try:
                    os.remove(tmp_in_path)
                    os.remove(tmp_out_full)
                    os.remove(tmp_out_toc)
                except OSError: pass

            else:
                tmp_out_path = tmp_in_path.replace(".pdf", "_bookmarked.pdf")
                st.markdown("### 🔄 진행 현황")
                logger = StreamlitLogger()
                
                with st.spinner("PDF를 분석하고 책갈피를 생성 중입니다..."):
                    extracted_toc = process_pdf_bookmarks(tmp_in_path, tmp_out_path, SCAN_MODE, EXCLUDE_FOOTNOTES, TARGET_DEPTH, CUSTOM_LVL1, CUSTOM_LVL2, CUSTOM_LVL3, logger)
                    
                if extracted_toc:
                    st.session_state.logs_single = logger.logs
                    with open(tmp_out_path, "rb") as f: st.session_state.pdf_data_single = f.read()
                        
                try:
                    os.remove(tmp_in_path)
                    os.remove(tmp_out_path)
                except OSError: pass
        
        live_status_container.empty()

    if st.session_state.get('scan_mode_run') == "ALL" and st.session_state.get('pdf_data_full') and st.session_state.get('pdf_data_toc'):
        col1, col2 = st.columns(2)
        col1.markdown("#### 🔍 FULL_SCAN 진행 현황")
        col1.markdown(format_final_logs(st.session_state.logs_full, st.session_state.logs_toc), unsafe_allow_html=True)
        col2.markdown("#### 🔍 TOC_BASED 진행 현황")
        col2.markdown(format_final_logs(st.session_state.logs_toc, st.session_state.logs_full), unsafe_allow_html=True)
        
        st.success("✅ 'ALL' 모드 작업이 완료되었습니다! 아래에서 개별 다운로드하세요.")
        st.markdown("### 💾 파일 다운로드")
        dcol1, dcol2 = st.columns(2)
        dcol1.download_button("📥 FULL_SCAN 결과 다운로드", st.session_state.pdf_data_full, f"full_scan_{uploaded_file.name}", mime="application/pdf", use_container_width=True)
        dcol2.download_button("📥 TOC_BASED 결과 다운로드", st.session_state.pdf_data_toc, f"toc_based_{uploaded_file.name}", mime="application/pdf", use_container_width=True)

    elif st.session_state.get('scan_mode_run') in ["FULL_SCAN", "TOC_BASED"] and st.session_state.get('pdf_data_single'):
        st.markdown("### 🔄 진행 현황")
        st.markdown(format_final_logs(st.session_state.logs_single), unsafe_allow_html=True)
        st.success("✅ 작업이 완료되었습니다! 아래에서 결과를 확인하고 다운로드하세요.")
        
        st.markdown("### 💾 파일 다운로드")
        st.download_button("📥 책갈피가 추가된 PDF 다운로드", st.session_state.pdf_data_single, f"bookmarked_{uploaded_file.name}", mime="application/pdf")
