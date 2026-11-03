% 规则事实线第 3 步：复述和正本比。和 canon.lp、scope.lp 一起 load（canon/3 在 canon.lp 里）。
%   句式读出的原子（patterns.py 喂进来，第一个参数是句子的节点）：
%     says(节点,键,事实,主语)  only(节点,键,事实,主语)  says_not(节点,键,事实,主语)
%     member(节点,键,条目)  not_member(节点,键,条目)
%     prevails(节点,载体A,载体B)         以 A 为准
%     may(节点,角色,事,在场或不在场,可以或不可以)
%     handoff(节点,卡在项,角色)
%     only_members(节点,键,条目)  closed(节点,键)
%   hands_on(事实名)                     用户只定与确认，不亲手做的几种事实
% 合称在喂进来以前已经展开成各个角色：复述写「由架构师」就是三条 says，正本只有总架构师，另两个按 extra 报。
% 多值事实复述时只说一部分不报：规则里没有「正本有而复述没说」这一类（说了「只有」的 only_wrong、closed_missing 除外）。

#defined says/4.
#defined only/4.
#defined says_not/4.
#defined member/3.
#defined not_member/3.
#defined prevails/3.
#defined may/5.
#defined handoff/3.
#defined only_members/3.
#defined closed/2.
#defined hands_on/1.

% ---- 五类 ----
% 复述多说了正本没有的值；说是某清单的一员，正本里没有这一员，也算多说
extra(N,K,F,V) :- says(N,K,F,V), not canon(K,F,V).
extra(N,K,"理由",X) :- member(N,K,X), not canon(K,"理由",X).
% 说「只由」，正本里还有别人
only_wrong(N,K,F,V) :- only(N,K,F,_), canon(K,F,V), not only(N,K,F,V).
% 说「不」，正本里有
denied(N,K,F,V) :- says_not(N,K,F,V), canon(K,F,V).
% 说不是理由，正本里是
not_member_wrong(N,K,X) :- not_member(N,K,X), canon(K,"理由",X).
% 两处说的「以谁为准」方向相反，或者绕成一圈
above(A,B) :- prevails(_,A,B).
above(A,C) :- above(A,B), above(B,C).
precedence_cycle(A,B) :- above(A,B), above(B,A), A < B.

% ---- 三类 ----
% 在场可否：复述说可以，正本说不可以，或反过来
canon_may(X,"在场",W) :- canon(X,"在场可否",W).
canon_may(X,"不在场",W) :- canon(X,"不在场可否",W).
may_wrong(N,R,X,S,V) :- may(N,R,X,S,V), canon_may(X,S,W), V != W.
% 交给：复述交给的角色，正本没有
handoff_wrong(N,K,R) :- handoff(N,K,R), not canon(K,"交给",R).
% 穷尽清单：复述说只有这些，正本还有别的；或复述里有正本没有的
closed_missing(N,K,V) :- closed(N,K), canon(K,"理由",V), not only_members(N,K,V).
closed_extra(N,K,V) :- only_members(N,K,V), not canon(K,"理由",V).

% ---- 用户只定与确认（方案第 3.1 节）：规则里写用户改、建、删、写的，都是走样 ----
user_hands_on(N,K,F) :- says(N,K,F,"用户"), hands_on(F).

#show extra/4.
#show only_wrong/4.
#show denied/4.
#show not_member_wrong/3.
#show precedence_cycle/2.
#show above/2.
#show may_wrong/5.
#show handoff_wrong/3.
#show closed_missing/3.
#show closed_extra/3.
#show user_hands_on/3.
