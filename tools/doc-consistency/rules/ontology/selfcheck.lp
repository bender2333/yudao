% 本体自检（方案第 5.1 节第 1、2 类），事实由 doc_consistency/ontology/compile.py 从 canon.json、roles.json 编译。
% 只用分层写法；和 meta.lp、layers.lp 一起 load。

kind_name(K) :- kind(K,_).

% 每个种类有且只有一层，层是登记过的
kind_bad_layer(K,L) :- kind(K,L), not layer(L,_).
kind_two_layers(K,L1,L2) :- kind(K,L1), kind(K,L2), L1 < L2.

% 关系的两端种类存在；起点为空是表没有声明 node（待补，不是矛盾）
rel_no_domain(F,T) :- rel(F,"",_,_,T).
rel_bad_domain(F,D,T) :- rel(F,D,_,_,T), D != "", not kind_name(D).
rel_bad_range(F,R,T) :- rel(F,_,R,_,T), not kind_name(R).
rel_bad_card(F,C,T) :- rel(F,_,_,C,T), not card(C).

% 同名关系在几张表里声明：单多值、终点种类要一致
rel_card_mismatch(F,T1,T2) :- rel(F,_,_,C1,T1), rel(F,_,_,C2,T2), C1 != C2, T1 < T2.
rel_range_mismatch(F,R1,R2) :- rel(F,_,R1,_,_), rel(F,_,R2,_,_), R1 < R2.

% 实例的种类登记过；同一个名字不是两个种类的实例
inst_bad_kind(N,K) :- instance_of(N,K), not kind_name(K).
name_two_kinds(N,K1,K2) :- instance_of(N,K1), instance_of(N,K2), K1 < K2.

% 别名：一个别名只指一个东西；别名不能和另一个实例重名
alias_clash(A,N1,N2) :- alias(A,N1,_), alias(A,N2,_), N1 < N2.
named(N) :- instance_of(N,_).
alias_shadows(A,N) :- alias(A,N,_), named(A), A != N.
alias_dangling(A,N,S) :- alias(A,N,S), not named(N).

% 合称的成员是角色
group_bad_member(G,M) :- group(G,M), not instance_of(M,"角色").

problem(m3) :- m3_bad_owner(_,_).
problem(m3) :- m3_bad_card(_,_,_).

% ---- 重新建模加的（方案第 10.1 节「重新建模」）----
% 「关于」：第 1 节的一行关于哪些载体；两端要对
about_bad_source(R,C) :- about(R,C,_), not instance_of(R,"事实").
about_bad_target(R,C) :- about(R,C,_), not instance_of(C,"载体").
has_about(R) :- about(R,_,_).
has_about(R) :- located_in(R,_).
located_bad(R,P) :- located_in(R,P), not instance_of(R,"事实").
% 待补：管一件事却说不出它关于哪个载体、放在哪个路径（只提醒）
fact_no_carrier(R) :- instance_of(R,"事实"), not has_about(R).

% 以谁为准：两边都是载体；不许成环（甲优先于乙，乙又优先于甲）
prevail_bad(W,L) :- prevails(W,L), not instance_of(W,"载体").
prevail_bad(W,L) :- prevails(W,L), not instance_of(L,"载体").
before(A,B) :- prevails(A,B).
before(A,C) :- before(A,B), prevails(B,C).
prevail_cycle(A,B) :- before(A,B), before(B,A), A < B.

% overlay.json 的声明：canon.json 后来自己声明了同一张表，一样就提醒删掉，不一样就报冲突
overlay_conflict(T,O,C) :- overlay_node(T,O), canon_node(T,C), O != C.
overlay_redundant(T) :- overlay_node(T,O), canon_node(T,O).
