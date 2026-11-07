/** 配置与命令行参数。 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
export const EXAMPLE_CONFIG = path.resolve(here, '../../config.example.json');

export function readConfig(file) {
  try { return JSON.parse(fs.readFileSync(file, 'utf8').replace(/^﻿/, '')); } catch { return null; }
}

/** `--milestone X` 可重复；没有时读 <root>/.ralph/architect/config.json 的 scope.milestones。 */
export function milestonesFromArgs(argv, root = process.cwd()) {
  const out = [];
  for (let i = 0; i < argv.length; i += 1) if (argv[i] === '--milestone' && argv[i + 1]) out.push(argv[++i]);
  if (out.length) return out;
  return readConfig(path.join(root, '.ralph/architect/config.json'))?.scope?.milestones || [];
}

/** "$VAR" 取当前进程的同名变量，别的值原样。 */
export function resolveEnv(env = {}, source = process.env) {
  return Object.fromEntries(Object.entries(env).map(([k, v]) => [k, typeof v === 'string' && v.startsWith('$') ? (source[v.slice(1)] ?? '') : v]));
}
