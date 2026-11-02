// 首页的楼与地下室机房的声明表（画面与播放设计说明第 5.1 节）：每种动作的级别（tier）与声明的最短时长（ms）。
// 楼里的动作都是闪光与包裹，不占用任何小人（时间线里不占参与方，互相不等）；动作怎么演写在 building.js
(function () {
  'use strict';
  const P = window.Y13.pixel;

  P.buildingDecl = {
    kinds: {
      // 楼：关键事实时这一层闪一下（颜色写在动作里），采纳时撒彩带，远程动作与部署的包裹沿通往机房的管线走
      floor_flash: { tier: 'normal', ms: 1200 },
      celebrate: { tier: 'key', ms: 1200 },
      shaft: { tier: 'normal', ms: 900 }
    },
    machineKinds: {
      // 机房：设备闪光（颜色写在动作里），包裹沿项目的管线到设备
      machine_flash: { tier: 'normal', ms: 1200 },
      machine_send: { tier: 'normal', ms: 900 }
    }
  };
})();
