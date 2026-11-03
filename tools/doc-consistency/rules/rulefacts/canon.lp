% 规则事实线：正本表格读出的事实、一条事实两处正本、正本点名的角色读不读得到。
%   canon_table(表)          声明为正本的表
%   in_file(表,文件)         表所在的文件
%   cell(表,键,事实,值)      读表读出的事实；角色格已经展开合称
%   role_fact(表,事实)       值是角色的事实
%   key_role(表)             键本身是角色的表（第 2 节角色表）
%   role(角色)、reads(角色,文件)  来自阅读范围（scope.lp 与 scaffold_facts）
% 一起 load scope.lp。

#defined canon_table/1.
#defined in_file/2.
#defined cell/4.
#defined role_fact/2.
#defined key_role/1.
#defined role/1.
#defined reads/2.

canon(K,F,V) :- cell(T,K,F,V), canon_table(T).

% 一条事实只归一处
dup_canon(K,F,T1,T2) :- cell(T1,K,F,_), cell(T2,K,F,_), T1 < T2.
dup_side(K,F,T) :- dup_canon(K,F,T,_).
dup_side(K,F,T) :- dup_canon(K,F,_,T).
% 两处里只有这一处有的值
only_in(K,F,V,T) :- dup_side(K,F,T), cell(T,K,F,V), dup_side(K,F,T2), T2 != T, not cell(T2,K,F,V).

% 表 T 的角色列里出现了角色 R
named(T,R) :- cell(T,_,F,R), role_fact(T,F).
named(T,K) :- cell(T,K,_,_), key_role(T).
% 正本点名的角色读不到正本所在的文件。role/1 只有 agent：roles.json 里 agent 为 false 的角色（用户）
% 不读规则文件，不对它算读不到；named 仍然包含它，矩阵里标「点名」。
unreachable(R,T) :- canon_table(T), in_file(T,F), named(T,R), role(R), not reads(R,F).

#show canon/3.
#show dup_canon/4.
#show only_in/4.
#show named/2.
#show unreachable/2.
