# 三个部门给用户看的叙述用中文（工单 #732）。
# 质检的结论偶尔用越南语写，用户在自己的资料页上读到的是一整段看不懂的文字，
# 而那段话恰恰写着「为什么不能放行」。这是 prompt 的责任：三个部门的 prompt 都要写明
# 「给用户看的叙述用中文；代码、命令、路径、标识符与引用的原文保持原样」。
#
# 这里检查的是规则还在不在，不是那句措辞本身：措辞以后可以改，规则不能被删掉。

import pytest

from harness.definitions import DEFINITIONS
from harness.models import DEPARTMENTS


@pytest.mark.parametrize("department", DEPARTMENTS)
def test_department_prompt_tells_the_department_to_write_for_the_user_in_chinese(department):
    prompt = DEFINITIONS.role(department).prompt
    # 规则的两半：叙述用中文；代码、命令、路径、标识符与引用的原文不动
    assert "用中文写" in prompt, department
    assert "代码、命令、路径、标识符与引用的原文保持原样" in prompt, department
