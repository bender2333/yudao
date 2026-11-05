// 试用工具自测用的小页面：一个由 React 渲染的受控输入框与一个会发请求的按钮。
//
// 用例用它们断言「工具真的清空了输入框」「点击真的触发了 React 的 onClick 并发出请求」，
// 而不是「坐标对」或「元素存在」。由浏览器测试在运行时复制到 client/.tmp 下，交给 Vite 的模块
// 服务器加载（React 来自 client 的依赖，与产品页面同一套机制）。
import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';

function App() {
  // 有原值的受控输入：React 的 state 是唯一事实，输入框的值由它写回
  const [search, setSearch] = useState('ag/gemini-3.8');
  // 空输入
  const [empty, setEmpty] = useState('');
  // Enter 提交的表单
  const [submitted, setSubmitted] = useState('no');
  // 按钮被点击的次数：React 的 onClick 真的跑到时才会增加
  const [clicks, setClicks] = useState(0);
  return (
    <>
      <h1>试用工具自测页</h1>
      <label>
        候选搜索
        <input id="search" type="search" value={search} onChange={(event) => setSearch(event.target.value)} />
      </label>
      <output id="search-state">{search}</output>
      <label>
        空输入
        <input id="empty" type="text" value={empty} onChange={(event) => setEmpty(event.target.value)} />
      </label>
      <output id="empty-state">{empty}</output>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          setSubmitted('yes');
          fetch('/api/submit', { method: 'POST' }).catch(() => {});
        }}
      >
        <input id="form-field" type="text" />
        <button type="submit">提交</button>
        <output id="submit-state">{submitted}</output>
      </form>
      <button
        type="button"
        onClick={() => {
          setClicks((previous) => previous + 1);
          fetch('/api/candidates', { method: 'POST' }).catch(() => {});
        }}
      >
        刷新模型列表
      </button>
      <output id="click-state">{clicks}</output>
    </>
  );
}

createRoot(document.getElementById('root')).render(<App />);
