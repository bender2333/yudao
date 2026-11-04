% 分层（方案第 3.1 节、第 5.1 节第 3 类）：上层代码不许点名下层概念的实例。
% 事实由 doc_consistency/ontology/layering.py 提取；和 layers.lp、selfcheck 的种类事实一起 load。
layer_violation(Path,Line,Inst,K,Scope) :-
    code_mentions(Path,Line,Inst,Scope), instance_of(Inst,K), kind(K,KL), layer(KL,NK), NK > 0,
    module_layer(Path,ML), layer(ML,NM), NM < NK.

% 共用概念，不共用实例（方案第 10.1 节）：脚手架的实例只住在脚手架里，内核代码不点名它们
scaffold_leak(Path,Line,Inst,K,Scope) :-
    code_mentions(Path,Line,Inst,Scope), instance_of(Inst,K), kind(K,"scaffold"), module_layer(Path,_).
