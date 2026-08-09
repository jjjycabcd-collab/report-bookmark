# ======================================================================
        # 기존 4-A, 4-B 전체를 아래의 통합 코드로 교체해 주세요.
        # ======================================================================
        st_logger.print("\n4. [최종 방어선] 1~3 depth 시퀀스/페이지 역전 검증 및 동적 레벨 할당 중...")
        strict_items = []
        
        current_1d_title = None
        is_current_1d_failed = False
        
        depth1_type = None
        depth1_last_num = 0
        depth1_last_page = -1

        # 2-depth와 3-depth를 동적으로 추적하기 위한 통합 상태 변수
        current_seq_state = {2: 0, 3: 0}
        current_seq_type = {2: None, 3: None}
        current_font_profile = {2: None, 3: None} 
        
        for item in resolved_items:
            original_lvl = item['level']
            if original_lvl == 99: continue 
            
            title = item['title']
            clean_t = CLEAN_PATTERN.sub('', title).lower()
            
            # [유령 항목 및 명시적 1-depth 처리]
            if is_ghost_title(clean_t, item['page_idx']) or title in ['표지', '목차', '참고문헌']:
                item['level'] = 1
                strict_items.append(item)
                current_1d_title = title
                is_current_1d_failed = '[점검]' in title
                current_seq_state = {2: 0, 3: 0}
                current_seq_type = {2: None, 3: None}
                current_font_profile = {2: None, 3: None}
                depth1_type = None; depth1_last_num = 0; depth1_last_page = -1
                continue
                
            st_type, sn = get_seq_info(title.replace('[점검] ', ''))
            
            # [기존 1-depth 유효성 검사 완벽 유지]
            if original_lvl == 1:
                is_valid_1depth = True
                if st_type and sn is not None:
                    is_from_toc = (item.get('toc_idx', 999) != 999)
                    
                    if is_from_toc:
                        depth1_type = st_type
                        depth1_last_num = sn
                        depth1_last_page = item['page_idx']
                    else:
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
                    is_current_1d_failed = '[점검]' in title
                    current_seq_state = {2: 0, 3: 0}
                    current_seq_type = {2: None, 3: None}
                    current_font_profile = {2: None, 3: None}
                    strict_items.append(item)
                continue
                
            # ==========================================================
            # [핵심 변경] 하위 항목(2-depth & 3-depth) 동적 할당 및 검증
            # ==========================================================
            if is_current_1d_failed or not current_1d_title: continue
            if st_type is None or sn is None: continue

            item_profile = (round(item.get('f_size', 0.0), 1), item.get('flags', 0), item.get('color', 0), item.get('f_name', ''))
            is_from_toc = (item.get('toc_idx', 999) != 999)
            
            assigned_level = None
            is_jump_error = False
            skip_item = False

            # [규칙 1] 1-depth 아래에 처음 등장하는 시퀀스는 무조건 2-depth로 셋팅
            if current_seq_type[2] is None:
                if sn > 1: is_jump_error = True
                current_seq_type[2] = st_type
                current_seq_state[2] = sn
                current_font_profile[2] = item_profile
                assigned_level = 2
                
            # [규칙 2] 기존 2-depth 기호 체계와 동일한 경우
            elif current_seq_type[2] == st_type:
                b_size, b_flags, b_color, b_name = current_font_profile[2]
                i_size, i_flags, i_color, i_name = item_profile
                font_match = is_from_toc or (abs(b_size - i_size) <= 0.5 and clean_fname(b_name) == clean_fname(i_name) and b_color == i_color)
                
                if font_match:
                    if sn == current_seq_state[2] + 1:
                        assigned_level = 2
                        current_seq_state[2] = sn
                        # 2-depth가 갱신되면 진행 중이던 3-depth 체계는 초기화
                        current_seq_type[3] = None; current_seq_state[3] = 0; current_font_profile[3] = None
                    elif sn > current_seq_state[2] + 1:
                        assigned_level = 2
                        current_seq_state[2] = sn
                        is_jump_error = True
                        current_seq_type[3] = None; current_seq_state[3] = 0; current_font_profile[3] = None
                    else:
                        skip_item = True
                else:
                    skip_item = True
                    
            # [규칙 3] 2-depth 체계와 다르고, 3-depth 탐색이 켜져 있는 경우
            else:
                if MAX_DEPTH >= 3:
                    # 2-depth 등장 이후 처음 나타나는 다른 기호는 3-depth로 셋팅
                    if current_seq_type[3] is None:
                        if sn > 1: is_jump_error = True
                        current_seq_type[3] = st_type
                        current_seq_state[3] = sn
                        current_font_profile[3] = item_profile
                        assigned_level = 3
                    # 기존 3-depth 기호 체계와 동일한 경우
                    elif current_seq_type[3] == st_type:
                        b_size, b_flags, b_color, b_name = current_font_profile[3]
                        i_size, i_flags, i_color, i_name = item_profile
                        font_match = is_from_toc or (abs(b_size - i_size) <= 0.5 and clean_fname(b_name) == clean_fname(i_name) and b_color == i_color)
                        
                        if font_match:
                            if sn == current_seq_state[3] + 1:
                                assigned_level = 3
                                current_seq_state[3] = sn
                            elif sn > current_seq_state[3] + 1:
                                assigned_level = 3
                                current_seq_state[3] = sn
                                is_jump_error = True
                            else:
                                skip_item = True
                        else:
                            skip_item = True
                else:
                    skip_item = True

            # 배제 대상(skip_item)이 아니라면 트리 리스트에 추가
            if not skip_item and assigned_level is not None:
                item['level'] = assigned_level
                if is_jump_error and not item['title'].startswith('[점검]'):
                    item['title'] = "[점검] " + item['title']
                strict_items.append(item)

        resolved_items = strict_items
        # ======================================================================
        # 여기서부터 기존 5. 요약문 등 유령항목 단일화... 부분이 이어집니다.
        # ======================================================================
