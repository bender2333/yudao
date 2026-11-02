% 角色阅读范围：每个角色从入口文件出发，读哪些文件。
%   role(角色)                      要算的角色
%   entry(角色,文件)                入口：规则文件与入口技能
%   scaffold(文件)                  脚手架文件（只有这些文件里的引用会继续往下读）
%   must_ref(角色,来源文件,目标文件)  必读的引用：先读章节、读/遵守/为准等指令句里的引用，并排除只对别的角色说的子句
%   any_ref(来源文件,目标文件)        任何链接与路径引用（可达，不等于必读）
%   size(文件,字符数)

#defined role/1.
#defined entry/2.
#defined scaffold/1.
#defined must_ref/3.
#defined any_ref/2.
#defined size/2.

% 必读只走一步：入口文件自己的指令算必读；必读文件里再指向的文件是按需查阅，不算
reads(R,F) :- entry(R,F).
reads(R,G) :- entry(R,F), must_ref(R,F,G).

reach(R,F) :- reads(R,F).
reach(R,G) :- reach(R,F), scaffold(F), any_ref(F,G).

chars_read(R,C) :- role(R), C = #sum{S,F : reads(R,F), size(F,S)}.
chars_reach(R,C) :- role(R), C = #sum{S,F : reach(R,F), size(F,S)}.

#show reads/2.
#show reach/2.
#show chars_read/2.
#show chars_reach/2.
