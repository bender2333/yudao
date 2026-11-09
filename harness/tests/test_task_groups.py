# 工单 #1661：任务分组（工作过程的任务与动作标题设计说明「任务」「任务分组」「老事件」）。
# 一个纯函数：一轮工作的工具调用记录 → 任务列表与每个动作的所属任务，从事实重算，不保存。
# 更新计划是普通的工具调用记录（工单 #1660），这里只读它写的整份计划与它在事件里的位置。
#
# 层：单元层（几条记录进、一份分组出，不读数据目录、不起服务）。
# 守 R3（工作过程读得懂：动作归到当时进行中的条目，没有进行中条目时的不编号、按时间留在两段任务之间）
# 与 R2（接口合同只增：分组只读已有的工具调用记录，不新增事件种类，不改写任何事实）。

from harness.app.task_groups import (PLAN_TOOL, TASK_COMPLETED, TASK_IN_PROGRESS, TASK_PENDING,
                                     TASK_REMOVED, Grouping, Task, ToolRecord, group_tasks)


def _plan(position: int, *entries: tuple[str, str], action_id: str = "plan",
          accepted: bool = True) -> ToolRecord:
    """一次更新计划的调用：整份计划按（那句话，状态）给出。"""
    return ToolRecord(position=position, action_id=action_id, name=PLAN_TOOL,
                      args={"plan": [{"content": content, "status": status}
                                     for content, status in entries]},
                      accepted=accepted)


def _action(position: int, action_id: str, name: str = "read_file") -> ToolRecord:
    """一个动作的工具调用记录：分组只看它的位置与身份。"""
    return ToolRecord(position=position, action_id=action_id, name=name, args={"path": "a.py"})


def _tasks(grouping: Grouping) -> list[tuple[int, str, str]]:
    return [(task.number, task.content, task.status) for task in grouping.tasks]


def test_the_status_words_are_the_ones_the_design_names():
    # R2：任务状态的取值是设计说明「任务」「任务分组」里的那几个词，接口与页面直接用它们
    assert {TASK_PENDING, TASK_IN_PROGRESS, TASK_COMPLETED, TASK_REMOVED} == {
        "待做", "进行中", "完成", "已从计划里去掉"}


def test_an_action_belongs_to_the_first_in_progress_entry_of_the_latest_plan():
    # R3（验收第 1 条）：一轮里更新三次计划，动作归到当时进行中的条目
    records = [
        _plan(10, ("写代码", "in_progress"), ("跑检查", "pending")),
        _action(11, "a-1"), _action(12, "a-2"),
        _plan(20, ("写代码", "completed"), ("跑检查", "in_progress")),
        _action(21, "b-1"),
        _plan(30, ("写代码", "completed"), ("跑检查", "completed"), ("提交交付", "in_progress")),
        _action(31, "c-1"),
    ]
    grouping = group_tasks(records)
    assert _tasks(grouping) == [(1, "写代码", TASK_COMPLETED),
                                (2, "跑检查", TASK_COMPLETED),
                                (3, "提交交付", TASK_IN_PROGRESS)]
    assert grouping.owners == {"a-1": 1, "a-2": 1, "b-1": 2, "c-1": 3}


def test_a_plan_sent_before_an_action_in_the_same_step_groups_that_action():
    # R3（验收第 1 条）：同一步里先发更新计划、后发动作时，动作归新计划；先发动作、后发计划的归旧计划。
    # 分组按事件位置算，不按两者谁先有结果算
    records = [
        _plan(10, ("旧的一条", "in_progress")),
        _action(11, "before"),
        _plan(12, ("新的一条", "in_progress"), action_id="plan-2"),
        _action(13, "after"),
    ]
    grouping = group_tasks(records)
    assert grouping.owners == {"before": 1, "after": 2}
    assert _tasks(grouping) == [(1, "旧的一条", TASK_REMOVED), (2, "新的一条", TASK_IN_PROGRESS)]


def test_the_first_of_several_in_progress_entries_wins():
    # R3（验收第 1 条）：不拒绝多条进行中（工单 #1660），归到排在最前的那一条
    records = [_plan(10, ("第一条", "in_progress"), ("第二条", "in_progress")),
               _action(11, "a-1")]
    grouping = group_tasks(records)
    assert grouping.owners == {"a-1": 1}
    assert _tasks(grouping) == [(1, "第一条", TASK_IN_PROGRESS), (2, "第二条", TASK_IN_PROGRESS)]


def test_the_same_sentence_is_one_task_and_a_reworded_one_is_new():
    # R3（验收第 2 条）：同一句话算同一条任务，几条动作归同一条；改了措辞的成为新的一条
    records = [
        _plan(10, ("写代码并跑检查", "in_progress")),
        _action(11, "a-1"),
        _plan(20, ("写代码并跑检查", "in_progress")),
        _action(21, "a-2"),
        _plan(30, ("写代码、跑检查，最后提交", "in_progress")),
        _action(31, "a-3"),
    ]
    grouping = group_tasks(records)
    assert grouping.owners == {"a-1": 1, "a-2": 1, "a-3": 2}
    assert _tasks(grouping) == [(1, "写代码并跑检查", TASK_REMOVED),
                                (2, "写代码、跑检查，最后提交", TASK_IN_PROGRESS)]


def test_an_action_between_two_tasks_is_unnumbered():
    # R3（验收第 3 条）：没有进行中条目时的动作不编号，按时间留在两段任务之间
    records = [
        _plan(10, ("写代码", "in_progress")),
        _action(11, "a-1"),
        _plan(20, ("写代码", "completed")),
        _action(21, "between"),
        _plan(30, ("写代码", "completed"), ("跑检查", "in_progress")),
        _action(31, "b-1"),
    ]
    grouping = group_tasks(records)
    assert grouping.owners == {"a-1": 1, "b-1": 2}
    assert "between" not in grouping.owners
    assert _tasks(grouping) == [(1, "写代码", TASK_COMPLETED), (2, "跑检查", TASK_IN_PROGRESS)]


def test_tasks_never_in_progress_come_last_and_dropped_ones_say_so():
    # R3（验收第 2 条）：从没进行过的排在最后；后来的计划里没有了的写「已从计划里去掉」；
    # 状态取最后一次写的
    records = [
        _plan(10, ("写代码", "in_progress"), ("跑检查", "pending")),
        _action(11, "a-1"),
        _plan(20, ("写代码", "completed"), ("跑检查", "pending")),
        _action(21, "between"),
        _plan(30, ("写代码", "completed"), ("提交交付", "in_progress")),
        _action(31, "a-2"),
    ]
    grouping = group_tasks(records)
    assert _tasks(grouping) == [(1, "写代码", TASK_COMPLETED),
                                (2, "提交交付", TASK_IN_PROGRESS),
                                (3, "跑检查", TASK_REMOVED)]
    assert grouping.owners == {"a-1": 1, "a-2": 2}


def test_the_order_is_the_first_time_each_task_was_in_progress():
    # R3（验收第 2 条）：顺序按第一次进行中的时间排，不按第一次写下的顺序排
    records = [
        _plan(10, ("跑检查", "pending"), ("写代码", "pending")),
        _plan(20, ("跑检查", "pending"), ("写代码", "in_progress")),
        _plan(30, ("跑检查", "in_progress"), ("写代码", "completed")),
    ]
    grouping = group_tasks(records)
    assert _tasks(grouping) == [(1, "写代码", TASK_COMPLETED), (2, "跑检查", TASK_IN_PROGRESS)]


def test_a_round_without_a_plan_has_no_tasks_and_no_owners():
    # R3（验收第 5 条）：一轮没有计划时任务列表为空，动作不带所属任务（页面平铺）
    grouping = group_tasks([_action(10, "a-1"), _action(11, "a-2")])
    assert grouping == Grouping(tasks=(), owners={})


def test_a_rejected_plan_does_not_replace_the_plan_in_force():
    # R3（自定的边界）：格式错误的更新计划是工具结果里的错误，不当成计划；分组仍按上一份已接受的计划
    records = [
        _plan(10, ("写代码", "in_progress")),
        _plan(20, action_id="plan-bad", accepted=False),
        _action(21, "a-1"),
    ]
    grouping = group_tasks(records)
    assert grouping.owners == {"a-1": 1}
    assert _tasks(grouping) == [(1, "写代码", TASK_IN_PROGRESS)]


def test_an_empty_plan_takes_the_tasks_out_of_plan():
    # R3（验收第 2 条）：空列表清空计划（工具定义里写明），之前写过的任务写「已从计划里去掉」，之后没有进行中条目
    records = [
        _plan(10, ("写代码", "in_progress")),
        _action(11, "a-1"),
        _plan(20, action_id="plan-empty"),
        _action(21, "after-clear"),
    ]
    grouping = group_tasks(records)
    assert grouping.owners == {"a-1": 1}
    assert _tasks(grouping) == [(1, "写代码", TASK_REMOVED)]


def test_the_plan_calls_are_not_actions_and_never_get_an_owner():
    # R3（验收第 5 条）：更新计划自己不单独成行——它不在归属里，输出只有动作
    records = [_plan(10, ("写代码", "in_progress")), _action(11, "a-1")]
    grouping = group_tasks(records)
    assert set(grouping.owners) == {"a-1"}
    assert all(task.number >= 1 for task in grouping.tasks)


def test_records_may_come_in_any_order():
    # R2：纯函数，按事件位置排，输入的顺序不影响结论
    entries = [
        _plan(10, ("写代码", "in_progress")),
        _action(11, "a-1"),
        _plan(20, ("写代码", "completed"), ("跑检查", "in_progress"), action_id="plan-2"),
        _action(21, "a-2"),
    ]
    assert group_tasks(entries) == group_tasks(list(reversed(entries)))


def test_a_plan_entry_without_a_known_status_is_shown_as_pending():
    # R3（自定的边界）：认不出的状态防御性地按「待做」显示，不丢这一条，也不当成进行中
    records = [ToolRecord(position=10, action_id="plan", name=PLAN_TOOL,
                          args={"plan": [{"content": "写代码", "status": "doing"}]}),
               _action(11, "a-1")]
    grouping = group_tasks(records)
    assert _tasks(grouping) == [(1, "写代码", TASK_PENDING)]
    assert grouping.owners == {}


def test_tasks_carry_the_sentence_exactly_as_the_role_wrote_it():
    # R3：任务的那句话原样给出（不在投影里改写措辞），编号从 1 起、连续
    records = [_plan(10, ("把 orders 的分页改掉", "in_progress")),
               _plan(20, ("把 orders 的分页改掉", "completed"), ("补一条回归用例", "pending"),
                     action_id="plan-2")]
    grouping = group_tasks(records)
    assert [task.number for task in grouping.tasks] == [1, 2]
    assert [task.content for task in grouping.tasks] == ["把 orders 的分页改掉", "补一条回归用例"]
    assert grouping.tasks[0] == Task(number=1, content="把 orders 的分页改掉", status=TASK_COMPLETED)

def test_leading_and_trailing_spaces_do_not_make_a_new_task():
    # R3（自定的边界）：同一句话带首尾空白仍是同一条任务；任务里给的是去掉首尾空白以后的那句话
    records = [
        _plan(10, ("写代码", "in_progress")),
        _action(11, "a-1"),
        _plan(20, ("  写代码  ", "in_progress"), action_id="plan-2"),
        _action(21, "a-2"),
    ]
    grouping = group_tasks(records)
    assert _tasks(grouping) == [(1, "写代码", TASK_IN_PROGRESS)]
    assert grouping.owners == {"a-1": 1, "a-2": 1}
