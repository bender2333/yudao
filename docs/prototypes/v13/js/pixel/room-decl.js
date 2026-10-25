// 部门房间的声明表（画面与播放设计说明第 5.1 节）：房间画面认的每种动作的级别（tier）与声明的最短时长（ms）。
// 动作怎么演写在 room.js 的 handlers；时长取自那段演出的主要部分（到可以被下一个动作接上的地方为止），走路的时间不算在里面。
// 进度一级不排队：思考、整理资料、有想法、等待重试、没有专门动作的工具调用，合并成工位上的一个持续姿势
(function () {
  'use strict';
  const P = window.Y13.pixel;

  const k = (tier, ms) => ({ tier, ms });
  P.roomDecl = {
    kinds: {
      // 关键：交接、询问与回答、采纳与质检结论、终止与等待、运维的发布回滚与故障
      handoff: k('key', 2400),
      send_letter: k('key', 3000),
      answer_letter: k('key', 2600),
      stamp_valid: k('key', 3200),
      seal: k('key', 3200),
      stamp_release: k('key', 3200),
      stamp_rework: k('key', 2400),
      paused: k('key', 1200),
      failed: k('key', 1400),
      done: k('key', 2200),
      cancelled: k('key', 2200),
      hold_card: k('key', 1200),
      hold_form: k('key', 1600),
      resume: k('key', 1000),
      wait_provider: k('key', 2600),
      deploy: k('key', 2400),
      rollback: k('key', 2200),
      fault: k('key', 3000),
      // 普通：开始一件事、读材料、写文件、运行命令与房间里的其余动作
      activate: k('normal', 1800),
      slump: k('normal', 1900),
      search: k('normal', 2900),
      read: k('normal', 1800),
      write: k('normal', 1800),
      run_command: k('normal', 1000),
      command_done: k('normal', 1200),
      toss: k('normal', 2200),
      submit: k('normal', 1000),
      returned: k('normal', 2500),
      inspect: k('normal', 3400),
      guidance_in: k('normal', 700),
      guidance_read: k('normal', 2600),
      guidance_reply: k('normal', 1700),
      compact: k('normal', 2500),
      compact_fail: k('normal', 2700),
      puzzled: k('normal', 2000),
      remote_run: k('normal', 3600),
      remote_unknown: k('normal', 4500),
      read_existing: k('normal', 3200),
      net_fetch: k('normal', 2100),
      mcp_press: k('normal', 900),
      trial: k('normal', 2200),
      self_test: k('normal', 2200),
      assign: k('normal', 1200),
      hand_back: k('normal', 1200),
      review: k('normal', 2600),
      explore: k('normal', 4000),
      replan: k('normal', 3100),
      semantic: k('normal', 900),
      // 进度
      fetch_folder: k('progress', 0),
      type_think: k('progress', 0),
      idea: k('progress', 0),
      retry_wait: k('progress', 0),
      tool_progress: k('progress', 0)
    }
  };
})();
