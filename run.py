# API Docs: https://reqable.com/docs/capture/addons

from reqable import *
import tempfile
import zipfile
import os
import io
import re
import json

def _normalize_question_text(text, max_words=10):
  """
  对给定的文本进行规范化处理，包括移除括号及其内容、下划线，以及限制单词数量。

  :param text: 需要被规范化的原始文本
  :param max_words: 规范化后文本中最大允许的单词数，默认为10
  :return: 规范化后的文本

  :raises: 无

  :note: 该函数内部使用正则表达式来处理文本。如果遇到异常情况，将返回原始文本的前200个字符。
  """
  if not text:
    return ''
  try:
    # remove parentheses and their contents
    s = re.sub(r'\([^)]*\)', '', text)
    # remove underscores
    s = s.replace('_', '')
    s = s.strip()
    # find words (English words, numbers, or CJK characters sequences)
    parts = re.findall(r"[A-Za-z0-9]+(?:'[A-Za-z0-9]+)?|[\u4e00-\u9fff]+", s)
    if not parts:
      # fallback: split on whitespace
      parts = re.split(r'\s+', s)
    short = parts[:max_words]
    return ' '.join(short)
  except Exception:
    return text[:200]

def extract_js_object(content, key_name):
  """
  从给定的字符串内容中提取与指定键名相关的JSON对象。

  详细说明：
  该函数在提供的字符串内容中查找特定键名，并尝试从该位置开始解析出一个完整的JSON对象。如果找到并成功解析了JSON对象，则返回该对象；否则，返回None。

  :param content: 要从中提取JSON对象的字符串。
  :type content: str
  :param key_name: 用于定位JSON对象起始位置的键名。
  :type key_name: str
  :return 如果成功找到并解析了JSON对象则返回该对象（作为字符串），否则返回None。
  :rtype Optional[str]
  """
  idx = content.find(key_name)
  if idx == -1:
    return None
  colon_idx = content.find(':', idx)
  if colon_idx == -1:
    return None
  i = colon_idx + 1
  while i < len(content) and content[i].isspace():
    i += 1
  if i >= len(content) or content[i] != '{':
    return None
  start = i
  stack = []
  in_single = in_double = False
  esc = False
  for j in range(i, len(content)):
    ch = content[j]
    if esc:
      esc = False
      continue
    if ch == '\\':
      esc = True
      continue
    if in_single:
      if ch == "'":
        in_single = False
      continue
    if in_double:
      if ch == '"':
        in_double = False
      continue
    if ch == "'":
      in_single = True
      continue
    if ch == '"':
      in_double = True
      continue
    if ch == '{':
      stack.append('{')
    elif ch == '}':
      if not stack:
        return None
      stack.pop()
      if not stack:
        return content[start:j+1]
  return None

def quote_object_keys(js_text):
  """
  将JavaScript对象中的无引号键转换为带双引号的键。

  :summary: 该函数遍历提供的JavaScript文本，查找并替换所有未使用引号包裹的对象键，
            将这些键用双引号包围。此处理有助于确保生成的JavaScript代码符合标准JSON格式。
  :returns: str -- 处理后的JavaScript字符串，其中所有的对象键都已加上双引号。

  :param js_text: 待处理的原始JavaScript文本
  :type js_text: str
  """
  out = []
  i = 0
  L = len(js_text)
  in_single = in_double = False
  esc = False
  while i < L:
    ch = js_text[i]
    if esc:
      out.append(ch)
      esc = False
      i += 1
      continue
    if ch == '\\':
      out.append(ch)
      esc = True
      i += 1
      continue
    if in_single:
      out.append(ch)
      if ch == "'":
        in_single = False
      i += 1
      continue
    if in_double:
      out.append(ch)
      if ch == '"':
        in_double = False
      i += 1
      continue
    if ch == "'":
      in_single = True
      out.append(ch)
      i += 1
      continue
    if ch == '"':
      in_double = True
      out.append(ch)
      i += 1
      continue

    if ch in '{,':
      out.append(ch)
      i += 1
      j = i
      while j < L and js_text[j].isspace():
        j += 1
      if j < L and re.match(r'[A-Za-z_$]', js_text[j]):
        k = j
        while k < L and re.match(r'[A-Za-z0-9_$]', js_text[k]):
          k += 1
        m = k
        while m < L and js_text[m].isspace():
          m += 1
        if m < L and js_text[m] == ':':
          key = js_text[j:k]
          out.append(js_text[i:j])
          out.append('"{}"'.format(key))
          i = k
          continue
      continue

    out.append(ch)
    i += 1
  return ''.join(out)

def js_to_json(js_text):
  """
  将JavaScript对象文本转换为有效的JSON格式字符串。

  :summary:
  此函数接收一段JavaScript对象的文本表示，处理其中的单引号和转义字符，
  并移除尾随逗号，从而生成一个符合JSON标准的字符串。
  处理过程中，所有键值对中的单引号会被替换为双引号以符合JSON规范，
  同时去除数组或对象定义末尾可能出现的多余逗号，确保输出可被JSON解析器正确读取。

  :param js_text: JavaScript对象的字符串形式
  :type js_text: str
  :return: 转换后的JSON兼容字符串
  :rtype: str

  :raises: 无
  """
  step1 = quote_object_keys(js_text)
  out = []
  i = 0
  L = len(step1)
  in_single = in_double = False
  esc = False
  while i < L:
    ch = step1[i]
    if esc:
      out.append(ch)
      esc = False
      i += 1
      continue
    if ch == '\\':
      out.append(ch)
      esc = True
      i += 1
      continue
    if in_single:
      if ch == "'":
        in_single = False
        out.append('"')
      else:
        if ch == '"':
          out.append('\\"')
        else:
          out.append(ch)
      i += 1
      continue
    if in_double:
      out.append(ch)
      if ch == '"':
        in_double = False
      i += 1
      continue
    if ch == "'":
      in_single = True
      out.append('"')
      i += 1
      continue
    if ch == '"':
      in_double = True
      out.append(ch)
      i += 1
      continue
    out.append(ch)
    i += 1
  step2 = ''.join(out)
  step3 = re.sub(r',\s*(?=[}\]])', '', step2)
  return step3

def process_questiondata_js_text(text):
  """
  处理给定的文本，从中提取并解析名为questionObj的JavaScript对象。

  :summary: 该函数尝试从输入文本中找到名为'questionObj'或以'var questionObj'开头的JavaScript对象字符串，
            并将其转换为JSON格式。如果成功，则返回解析后的字典；如果失败，则返回错误信息。
  :param text: 输入的文本字符串
  :returns: 返回一个元组，第一个元素是解析后的字典（若成功）或None（若失败），第二个元素是错误信息（若存在）或None（若无错误）
  :raises: 不直接抛出异常，但内部处理可能遇到的异常，并将异常信息作为返回值的一部分
  """
  js_obj_text = extract_js_object(text, 'questionObj')
  if js_obj_text is None:
    js_obj_text = extract_js_object(text, 'var questionObj')
  if js_obj_text is None:
    return None, 'questionObj not found'
  json_like = js_to_json(js_obj_text)
  try:
    parsed = json.loads(json_like)
    return parsed, None
  except Exception as e:
    return None, f'JSON parse error: {e}'


def get_answer(qobj: dict):
  """
  从给定的qobj中提取问题类型、问题文本和答案集合。

  :summary: 该函数解析输入的qobj字典，根据不同的问题类型(qtype)处理问题文本(question_text)和答案(ans_collection)。支持多种问题类型及答案格式，包括但不限于直接字符串、列表、选项等，并对特定问题类型进行特殊处理。
  :param qobj: 包含问题信息的字典，可能包含'question_text', 'answer_text', 'qtype_id'等键
  :returns: 一个列表，包含问题类型(int), 处理后的问题文本(str), 和答案集合(list)
  :rtype: list

  .. note::
     - 函数内部使用了正则表达式来分割字符串形式的答案。
     - 对于某些特定问题类型(如109, 531, 108)，有额外的处理逻辑以正确提取相关信息。
     - 当没有明确指定答案时，尝试从问题列表中的子问题提取答案。
  """
  qtype = qobj.get('qtype_id') if 'qtype_id' in qobj else qobj.get('question_type')
  # use question_text as the prompt location for most types (normalize & truncate)
  question_text_raw = qobj.get('question_text', qobj.get('answer_text', ''))
  question_text = _normalize_question_text(question_text_raw)

  # locate candidate answer fields (prefer explicit fields).
  # Per requirement: ans_collection should come from 'answer_text'/'answer'/'ans' etc.
  candidate = None
  for key in ('answer_text', 'answer', 'ans', 'answers', 'answers_list', 'answersList', 'result', 'analysis'):
    if key in qobj and qobj.get(key) not in (None, ''):
      candidate = qobj.get(key)
      # 如果包含“参考答案二”，则截取其之前内容
      if isinstance(candidate, str) and '参考答案二' in candidate:
        candidate = candidate.split('参考答案二')[0]
      break

  def to_collection(x):
    if x is None:
      return []
    if isinstance(x, (list, tuple)):
      return list(x)
    if isinstance(x, (int, float)):
      return [x]
    if isinstance(x, str):
      s = x.strip()
      if not s:
        return []
      parts = re.split(r'[;；,，\|/\n\r]+', s)
      parts = [p.strip() for p in parts if p.strip()]
      if len(parts) <= 1:
        return [s]
      return parts
    return [x]

  # Special handling for qtype 109 (听选二): qt = child.question_text, ans = child.answer_text
  # Special handling for qtype 531: answers come from record_speak[0].content
  if qtype == 531:
    ans_collection = []
    recs = qobj.get('record_speak') or qobj.get('record_follow_read') or []
    if isinstance(recs, list) and len(recs) > 0:
      first = recs[0]
      if isinstance(first, dict):
        content = first.get('content') or first.get('content_en') or first.get('content_cn') or first.get('net_file')
      else:
        content = first
      if content:
        ans_collection = to_collection(content)
    return [589, question_text, ans_collection]

  if qtype == 109 or qtype == 110:
    question_list = qobj.get('questions_list') or qobj.get('questions') or qobj.get('question_list')
    qt_collection = []
    ans_collection = []
    if question_list and isinstance(question_list, (list, tuple)):
      for question in question_list:
        if isinstance(question, dict):
          qt = question.get('question_text') or question.get('question') or ''
          ans = question.get('answer_text') or question.get('answer') or question.get('ans') or ''
          if qt:
            qt_collection.append(_normalize_question_text(qt))
          if ans:
            options = question.get('options') or question.get('option_list') or []
            if isinstance(options, (list, tuple)):
              found = False
              for opt in options:
                if isinstance(opt, dict):
                  opt_id = opt.get('id') or opt.get('option_id')
                  if ans and str(opt_id) == str(ans):
                    opt_text = opt.get('content') or opt.get('text') or ''
                    if opt_text:
                      ans_collection.append(f"{ans}: {opt_text}")
                      found = True
                      break
              if not found:
                ans_collection.extend(to_collection(ans))
            # keep raw answer_text values (no normalize)

    return [qtype, qt_collection, ans_collection]
  
  if qtype == 108:
    # for qtype 108, use question_text as is, and extract answers from options marked as correct
    ans = qobj.get('answer_text') or qobj.get('answer') or qobj.get('ans')
    options = qobj.get('options') or qobj.get('option_list') or []
    ans_collection = []
    tokens = to_collection(ans)
    for tok in tokens:
      mapped = None
      try:
        if isinstance(options, (list, tuple)):
          for opt in options:
            if not isinstance(opt, dict):
              continue
            opt_id = opt.get('id') or opt.get('option_id')
            opt_text = opt.get('content') or opt.get('text') or opt.get('value') or ''
            if opt_id is not None and tok is not None and str(opt_id) == str(tok):
              mapped = f"{tok}: {opt_text}" if opt_text else str(tok)
              break
            if opt_text and str(opt_text).strip() == str(tok).strip():
              mapped = f"{opt_id or ''}: {opt_text}".strip()
              break
      except Exception:
        mapped = None
      ans_collection.append(mapped if mapped is not None else tok)
    return [qtype, question_text, ans_collection]

  if candidate is not None and candidate != '':
    ans_collection = to_collection(candidate)
  else:
    # fallback to extracting from possible question_list structures
    question_list = qobj.get('questions_list') or qobj.get('questions') or qobj.get('question_list')
    if question_list and isinstance(question_list, (list, tuple)):
      # collect answers from sub-questions (use child answer_text/answer/answers_list)
      collected = []
      for item in question_list:
        if isinstance(item, dict):
          if item.get('answer_text'):
            collected.extend(to_collection(item.get('answer_text')))
          elif item.get('answer'):
            collected.extend(to_collection(item.get('answer')))
          elif item.get('ans'):
            collected.extend(to_collection(item.get('ans')))
          elif item.get('answers_list'):
            for ans in item.get('answers_list'):
              if isinstance(ans, dict):
                collected.extend(to_collection(ans.get('content') or ans.get('text') or ans.get('value')))
              else:
                collected.extend(to_collection(ans))
      if collected:
        ans_collection = collected
      else:
        ans_collection = []
    else:
      ans_collection = to_collection(question_text)

  return [qtype, question_text, ans_collection]


def onRequest(context, request):
  # Print url to console and return request unchanged
  # print('request url ' + context.url)
  return request


def onResponse(context, response):
  """
  从响应体中读取并处理Pc.zip文件，提取其中的题目数据，并将答案整理输出到临时文本文件中。

  :section Summary:
  该函数主要执行以下步骤：
  1. 从响应体中尝试获取Pc.zip的字节数据。
  2. 将字节数据解压至临时目录。
  3. 在解压后的文件中查找包含题目的文件夹。
  4. 读取并解析`questionData.js`文件中的内容，提取答案信息。
  5. 对提取的答案按题型进行排序。
  6. 将排序后的答案写入临时文本文件，并尝试用默认程序打开该文件。

  :param context: 上下文对象
  :param response: 包含Pc.zip文件的响应对象
  :return: 处理后的响应对象

  :section Parameters:
  - `context`: 与请求相关的上下文信息
  - `response`: HTTP响应对象，其body部分预期为Pc.zip文件或指向该文件的路径

  :section Returns:
  - 返回原始的`response`对象。如果成功处理了zip文件，则在本地生成了一个包含答案的临时文本文件。

  :section Raises:
  - 可能因I/O操作失败、文件格式错误等原因抛出异常，但这些异常会被捕获并在控制台打印错误消息，不会直接传播给调用者。
  """
  # Attempt to get raw bytes from response.body (expected to be Pc.zip)
  body = response.body
  # print('[addons] reading response.body...')
  zip_bytes = None
  try:
    if body is None:
      print('[addons] response.body is None')
    elif isinstance(body, (bytes, bytearray)):
      zip_bytes = bytes(body)
    elif hasattr(body, 'read'):
      try:
        zip_bytes = body.read()
        if isinstance(zip_bytes, str):
          zip_bytes = zip_bytes.encode('utf-8')
      except Exception:
        zip_bytes = getattr(body, 'bytes', None)
        if isinstance(zip_bytes, str):
          zip_bytes = zip_bytes.encode('utf-8')
    elif isinstance(body, str) and os.path.isfile(body):
      with open(body, 'rb') as bf:
        zip_bytes = bf.read()
    elif hasattr(body, 'file') and isinstance(body.file, str) and os.path.isfile(body.file):
      with open(body.file, 'rb') as bf:
        zip_bytes = bf.read()
    else:
      candidate = getattr(body, 'bytes', None)
      if isinstance(candidate, (bytes, bytearray)):
        zip_bytes = bytes(candidate)
      elif isinstance(candidate, str):
        zip_bytes = candidate.encode('utf-8')
      else:
        try:
          zip_bytes = bytes(body)
        except Exception:
          zip_bytes = None
  except Exception as ex:
    print(f'[addons] error reading response.body: {ex}')

  if not zip_bytes:
    return response

  try:
    with tempfile.TemporaryDirectory() as td:
      zip_path = os.path.join(td, 'Pc.zip')
      with open(zip_path, 'wb') as zp:
        zp.write(zip_bytes)
      try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
          zf.extractall(td)
      except zipfile.BadZipFile:
        print('[addons] Bad zip file in response.body')
        return response

      # find question folder
      question_root = os.path.join(td, 'questions')
      if not os.path.isdir(question_root):
        found = None
        for root, dirs, files in os.walk(td):
          for d in dirs:
            if d == 'questions':
              found = os.path.join(root, d)
              break
          if found:
            break
        if found:
          question_root = found
      if not os.path.isdir(question_root):
        print('[addons] No "question" folder found inside Pc.zip')
        return response
      

      ans_list = []
      for root, dirs, files in os.walk(question_root):
        for fname in files:
          if fname == 'questionData.js':
            full = os.path.join(root, fname)
            try:
              with io.open(full, 'r', encoding='utf-8') as f:
                text = f.read()
            except Exception:
              with io.open(full, 'r', encoding='latin1') as f:
                text = f.read()
            # Remove any HTML tags from the file content before further processing
            try:
              text = re.sub(r'<[^>]+>', '', text)
            except Exception:
              pass

            parsed, err = process_questiondata_js_text(text)
            if not parsed:
              continue
            if err:
              print(f'[addons] {err}')
            else:
              ans_struct = get_answer(parsed)
              ans_list.append(ans_struct)
              if not ans_struct:
                print('[addons] getAnswer returned empty or None')
                print(json.dumps(parsed, ensure_ascii=False))
              else:
                # print('getAnswer: ' + json.dumps(ans_struct, ensure_ascii=False))
                pass


    # Sort ans_list by qtype (first element) ascending. Each entry is [qtype, question_text, ans_collection]
    try:
      ans_list.sort(key=lambda it: (it[0] if (isinstance(it, (list, tuple)) and len(it) > 0 and isinstance(it[0], (int, float))) else float('inf')))
    except Exception:
      # fallback: keep original order if sorting fails
      pass

    print("由于Pc包所有文件均为Hash命名，只能做到对题型排序。请检查答案和天学网的题目是否一致。")
    last_qtype = None
    display_lines = []
    for ans in ans_list:
      # print separator when question type changes
      try:
        current_q = ans[0]
      except Exception:
        current_q = None
      if last_qtype != current_q:
        sep = "----------------"
        print(sep + "\n")
        # also record separator into output file so groups are visible there
        display_lines.append(sep)
      last_qtype = current_q

      # Replace qtype 108 with "听后选择" in the first element if applicable
      if isinstance(ans, (list, tuple)) and len(ans) > 0:
        if ans[0] == 108:
          ans[0] = "听后选择"
        elif ans[0] == 109 or ans[0] == 110:
          ans[0] = "听后双项选择"
        elif ans[0] == 532:
          ans[0] = "听后转述"
        elif ans[0] == 583:
          ans[0] = "听后填空"
        elif ans[0] == 588:
          ans[0] = "朗读短文"
        elif ans[0] == 589:
          ans[0] = "回答问题"
      # collect formatted lines for output file
      try:
        display_lines.append(json.dumps(ans, ensure_ascii=False))
      except Exception:
        display_lines.append(str(ans))

    # write collected answers to a temp txt file and open with default application
    try:
      if display_lines:
        out_path = None
        try:
          with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False, suffix='.txt') as tf:
            tf.write("由于Pc包所有文件均为Hash命名，只能做到对题型排序。请检查答案和天学网的题目是否一致。\n\n")
            tf.write('\n\n'.join(display_lines))
            out_path = tf.name
        except Exception as e:
          print(f'[addons] error writing answers file: {e}')
        if out_path:
          try:
            # Windows: open with default associated program
            os.startfile(out_path)
          except Exception:
            print(f'[addons] saved answers to: {out_path}')
    except Exception as e:
      print(f'[addons] error preparing answers file: {e}')
  except Exception as e:
    print(f'[addons] unexpected error processing zip: {e}')

  return response