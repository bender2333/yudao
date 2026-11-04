% M3：本体的写法本身，也用同一套事实描述自己（方案第 4.2 节、第 5.1 节第 1 类）。
meta_kind(kind). meta_kind(relation). meta_kind(field).
field(kind,layer,"single"). field(kind,is_a,"multi").
field(relation,domain,"single"). field(relation,range,"single"). field(relation,card,"single").
field(field,owner,"single"). field(field,card,"single").
card("single"). card("multi").

% M3 符合它自己：每个字段的主人是登记过的元种类，单多值是登记过的取值
m3_bad_owner(O,F) :- field(O,F,_), not meta_kind(O).
m3_bad_card(O,F,C) :- field(O,F,C), not card(C).
