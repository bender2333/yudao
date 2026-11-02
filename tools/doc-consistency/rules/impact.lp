% 改动影响：改了某个文件或小节，哪些节点引用它、提到它，并按角色分组。
%   target(节点或文件)      被改的目标
%   parent(子节点,父节点)   节点的包含关系（小节在文件里，表格行在小节里）
%   edge(来源节点,目标,种类)  索引里的引用边
%   defines(节点,实体)      这个节点定义了某个名字（表格行定义标签或技能，技能文件定义技能）
%   mention(节点,实体)      这个节点的文字里提到了某个名字
%   node_file(节点,文件)    节点所在的文件
% 阅读范围来自 scope.lp 的 reads 与 reach。

#defined target/1.
#defined parent/2.
#defined edge/3.
#defined defines/2.
#defined mention/2.
#defined node_file/2.

in_target(T) :- target(T).
in_target(C) :- in_target(P), parent(C,P).

hit(N,ref,D) :- edge(N,D,_), in_target(D), not in_target(N).
hit(N,mention,E) :- in_target(X), defines(X,E), mention(N,E), not in_target(N).

affected(N) :- hit(N,_,_).

% 必读：节点所在的文件在这个角色的必读范围里；可达：只在可达范围里
seen_must(R,N) :- affected(N), node_file(N,F), reads(R,F).
seen_link(R,N) :- affected(N), node_file(N,F), reach(R,F), not reads(R,F).
unseen(N) :- affected(N), node_file(N,F), not reach(_,F).

#show hit/3.
#show seen_must/2.
#show seen_link/2.
#show unseen/1.
