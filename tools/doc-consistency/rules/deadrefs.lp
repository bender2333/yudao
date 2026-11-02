% 死引用：技能、标签、文件路径。只用分层写法：否定只依赖下面已经算完的事实。
% 事实由程序提供：
%   skill(名)           技能目录里有的技能
%   external_skill(名)  内置技能与用户级技能（数据文件 known-external.json）
%   label(名)           GitHub 标签快照
%   skill_ref(节点,名,行) / label_ref(节点,名,行)   文档里引用的技能与标签
%   path_ref(节点,写法,行) / path_alive(节点,写法)   文档里写的文件路径，及程序按三处位置查到的结果

#defined skill/1.
#defined external_skill/1.
#defined label/1.
#defined skill_ref/3.
#defined label_ref/3.
#defined path_ref/3.
#defined path_alive/2.

known_skill(S) :- skill(S).
known_skill(S) :- external_skill(S).

dead_skill(N,S,L) :- skill_ref(N,S,L), not known_skill(S).
dead_label(N,X,L) :- label_ref(N,X,L), not label(X).
dead_path(N,P,L) :- path_ref(N,P,L), not path_alive(N,P).

#show dead_skill/3.
#show dead_label/3.
#show dead_path/3.
