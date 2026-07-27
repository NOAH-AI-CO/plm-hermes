import logging
import re
from dataclasses import dataclass
from typing import List

import httpx
from agent.ppt.prompt import get_main_py_init_content
from agent.ppt import llm
from config import api_config

logger = logging.getLogger(__name__)


# PPTXSDKDOC_URL = "http://localhost:10001/api/v1/get_pptxsdk_info" # 本地调试
PPTXSDKDOC_URL = api_config.PPTXSDKDOC_URL # 线上


PROTOCOL_NAME = "NOAHAI_EDIT_REPLACE_RANGE"
REPLACE_ACTION_NAME = "NOAHAI_EDIT_REPLACE_RANGE"


def get_edit_prompt() -> str:
    prompt = f"""
`{PROTOCOL_NAME}` 协议格式：

-----以下是 {PROTOCOL_NAME} 协议格式 -----
{REPLACE_ACTION_NAME}[start_line, end_line]
new_content
{REPLACE_ACTION_NAME}[start_line, end_line]
new_content
...
-----以上是 {PROTOCOL_NAME} 协议格式 -----

解释：
- 基本格式：使用 `{REPLACE_ACTION_NAME}[start_line, end_line]` 独占一行，表示将原始文件中从第 `start_line` 行到第 `end_line` 行（包含两端）的内容删除，并替换为紧跟在下方的新内容(new_content)。
- 行号基准：`start_line` 和 `end_line` 必须严格基于用户提供的带有行号的原文件（原文件会以 `cat -n` 的形式展示给你，你直接使用原文件中的行号即可）。**你在填写行号时，永远以当前给定的原文状态为准，绝对不要考虑你的编辑动作对行号产生的任何偏移影响。**
- 禁止行号倒置：必须保证 `start_line <= end_line`，绝对禁止 `start_line > end_line` 的情况，否则会报错。
- 允许有多个 `{REPLACE_ACTION_NAME}` 动作，每个动作代表一个编辑操作。
- 禁止多个动作的行号范围重叠：如果有多个 `{REPLACE_ACTION_NAME}` 动作，必须保证多个动作的行号范围不重叠，否则会报错。
- 空文件特殊规则：如果当前提供的原文件内容完全为空，你需要写入内容时，请将行号写为：`{REPLACE_ACTION_NAME}[0, 0]`。
- new_content 可以为空，表示删除行号范围内的内容。如果 new_content 为空，则表示删除行号范围内的内容，如果 new_content 不为空，则表示替换行号范围内的内容。

常见操作：
- 替换多行：`{REPLACE_ACTION_NAME}[10, 15]`，下方写上新的内容。
- 纯删除：`{REPLACE_ACTION_NAME}[100, 120]`，下方不写任何内容，直接紧跟下一个 `{REPLACE_ACTION_NAME}` 标签（如果有），或者直接结束。
- 纯插入（重要）：
  如果你想在第 5 行和第 6 行之间插入新内容，你必须选择替换第 5 行（或第 6 行）。
  例如，使用 `{REPLACE_ACTION_NAME}[5, 5]`，然后**在下方先一字不差地抄写第 5 行的原始内容，紧接着写上你要插入的新内容**。如果不抄写第 5 行的原始内容，原第 5 行的内容将会丢失！
- 在首行前插入新内容：直接替换首行内容(你的 new_content 最后一行要写一遍首行内容，不然这行内容就被删了)
- 在末尾添加新内容：直接替换最后那一行内容(你的 new_content 第一行要写一遍最后那一行内容，不然这行内容就被删了)

示例：

----- 以下是示例 -----
{REPLACE_ACTION_NAME}[11, 15]
hello
world
{REPLACE_ACTION_NAME}[30, 30]
hi
world
{REPLACE_ACTION_NAME}[35, 40]
----- 以上是示例 -----

解释：
上述示例共3个动作
动作1: 对第11行到第15行的内容进行删除然后替换为“hello\nworld”（删除原来的11至15行共5行内容，替换为hello和world这2行内容）
动作2: 对第30行的内容进行删除然后替换为“hi\nworld”（删除原来第30行内容共1行内容，替换为hi和world这2行内容）
动作3: 删除35行到第40行的内容

你的输出：
你的输出必须严格遵守`{PROTOCOL_NAME}` 协议格式，否则会报错。
禁止输出任何其他内容，包括但不限于：解释、说明、用代码块包裹输出、用markdown格式输出等等。你只能输出`{PROTOCOL_NAME}` 协议格式的内容。
    """
    return prompt.strip()


@dataclass(frozen=True)
class EditAction:
    start_line: int
    end_line: int
    new_lines: List[str]

    @property
    def new_content(self) -> str:
        return "\n".join(self.new_lines)


def parse_edit_actions(llm_response: str) -> List[EditAction]:
    """Parse LLM output in NOAHAI_EDIT_REPLACE_RANGE format."""
    lines = llm_response.splitlines()
    actions: List[EditAction] = []
    current_start = None
    current_end = None
    current_new_lines: List[str] = []
    seen_first_action = False

    action_line_re = re.compile(rf"^\s*{re.escape(REPLACE_ACTION_NAME)}\s*\[\s*(\d+)\s*,\s*(\d+)\s*\]\s*$")

    for line_index, line in enumerate(lines, start=1):
        match = action_line_re.match(line)
        if match:
            if seen_first_action:
                actions.append(
                    EditAction(
                        start_line=current_start,
                        end_line=current_end,
                        new_lines=current_new_lines,
                    )
                )

            current_start = int(match.group(1))
            current_end = int(match.group(2))
            current_new_lines = []
            seen_first_action = True
            continue

        if not seen_first_action:
            if line.strip():
                raise ValueError(f"第 {line_index} 行不是合法的编辑动作: {line!r}")
            continue

        current_new_lines.append(line)

    if seen_first_action:
        actions.append(
            EditAction(
                start_line=current_start,
                end_line=current_end,
                new_lines=current_new_lines,
            )
        )

    if not actions:
        raise ValueError("LLM 返回中没有找到任何编辑动作")

    return actions


def _validate_edit_actions(file_content: str, actions: List[EditAction]) -> None:
    line_count = len(file_content.splitlines())

    for action in actions:
        if action.start_line > action.end_line:
            raise ValueError(
                f"行号范围倒置: [{action.start_line}, {action.end_line}]"
            )

        if action.start_line == 0 or action.end_line == 0:
            if line_count != 0 or action.start_line != 0 or action.end_line != 0:
                raise ValueError(
                    f"只有空文件允许使用 [0, 0] 范围: "
                    f"[{action.start_line}, {action.end_line}]"
                )
            continue

        if action.start_line < 1:
            raise ValueError(f"start_line 必须大于等于 1: {action.start_line}")

        if action.end_line > line_count:
            raise ValueError(
                f"end_line 超出文件总行数 {line_count}: {action.end_line}"
            )

    sorted_actions = sorted(actions, key=lambda item: item.start_line)
    previous = None
    for action in sorted_actions:
        if previous is not None and action.start_line <= previous.end_line:
            raise ValueError(
                "编辑动作行号范围重叠: "
                f"[{previous.start_line}, {previous.end_line}] 和 "
                f"[{action.start_line}, {action.end_line}]"
            )
        previous = action


def apply_edit_actions(file_content: str, actions: List[EditAction]) -> str:
    """Apply parsed edit actions to file_content from bottom to top."""
    _validate_edit_actions(file_content, actions)

    newline = "\r\n" if "\r\n" in file_content else "\n"
    keep_final_newline = file_content.endswith(("\n", "\r"))
    lines = file_content.splitlines()

    for action in sorted(actions, key=lambda item: item.start_line, reverse=True):
        if action.start_line == 0 and action.end_line == 0:
            lines[0:0] = action.new_lines
            continue

        start_index = action.start_line - 1
        end_index = action.end_line
        lines[start_index:end_index] = action.new_lines

    new_content = newline.join(lines)
    if keep_final_newline and new_content:
        new_content += newline

    return new_content


def edit_content(file_content: str, llm_response: str) -> str:
    actions = parse_edit_actions(llm_response)
    return apply_edit_actions(file_content, actions)


async def get_prompt(main_py_content: str, stdout_stderr_content: str):
    async with httpx.AsyncClient() as client:
        response = await client.get(PPTXSDKDOC_URL)
        pptxsdkdoc = response.text
    edit_prompt = get_edit_prompt()
    main_py_init_content = get_main_py_init_content()
    main_py_content_cat_n = "\n".join(f"{i:>6}\t{line}" for i, line in enumerate(main_py_content.splitlines(), start=1))
    prompt = f"""
你是一个极其严谨的代码与文本编辑助手，你的任务是根据用户需求，对提供的原始文件内容(main.py)进行精确修改。
你必须且只能使用 `{PROTOCOL_NAME}` 协议格式来输出你的修改动作，`{PROTOCOL_NAME}` 协议格式是我自定义的格式，会在后续详细介绍。
你只能修改文件，你无法读取文件、删除文件、下载文件、浏览网页等等任何其他操作。
如果你认为无需任何修改，请直接在文件末尾添加一个空行，然后结束。（原因是你必须返回`{PROTOCOL_NAME}`协议格式的内容，即使无需任何修改，你也必须返回`{PROTOCOL_NAME}`协议格式的内容，所以直接在文件结尾添加一个空行即可）

---------------------------------------- 以下是 {PROTOCOL_NAME} 格式说明 ----------------------------------------
{edit_prompt}
---------------------------------------- 以上是 {PROTOCOL_NAME} 格式说明 ----------------------------------------

---------------------------------------- 以下是pptxsdk的说明 ----------------------------------------
{pptxsdkdoc}
---------------------------------------- 以上是pptxsdk的说明 ----------------------------------------

---------------------------------------- 以下是执行main.py返回的stdout和stderr ----------------------------------------
{stdout_stderr_content}
---------------------------------------- 以上是执行main.py返回的stdout和stderr ----------------------------------------

---------------------------------------- 以下是main.py应该遵循的结构 ----------------------------------------
{main_py_init_content}
---------------------------------------- 以上是main.py应该遵循的结构 ----------------------------------------

main.py的内容以`cat -n`的形式展示给你，注意行号左右的空白符不是文件内容.
---------------------------------------- 以下是main.py的当前实际内容 ----------------------------------------
{main_py_content_cat_n}
---------------------------------------- 以上是main.py的当前实际内容 ----------------------------------------

帮我修复main.py中的BUG，包括但不限于语法错误、缩进错误、字符串中双引号单引号未转义错误、使用了未定义的变量错误、变量名写错的错误、没有遵守"main.py应该遵循的结构"的错误等等。
不要仅修复stdout stderr中显示的错误，而是要检查main.py中是否还有其他BUG，一并修复。
你无需关注代码逻辑，你仅仅关注BUG。
现在请你输出你的修改动作，仅输出`{PROTOCOL_NAME}`协议格式的内容，禁止输出任何其他内容。请严格遵守`{PROTOCOL_NAME}`协议格式，否则会报错。
    """
    return prompt.strip()


async def fix_bug(main_py_content: str, stdout_stderr_content: str) -> str:
    fix_bug_prompt = await get_prompt(main_py_content, stdout_stderr_content)
    messages = [
        llm.role_system("You are a code editor"),
        llm.role_user(fix_bug_prompt),
    ]
    llm_response = await llm.async_chat(
        llm.LLMReq(
            model="google/gemini-3.1-pro-preview",
            messages=messages,
        )
    )
    llm_response = llm_response.choices[0].message.content
    logger.info(f"LLM 返回的修改动作:\n{llm_response}")
    new_content = edit_content(main_py_content, llm_response)
    return new_content
