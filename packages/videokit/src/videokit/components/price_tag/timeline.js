const b=P.beats;
const tl=gsap.timeline();
if(document.querySelector('.lw')){enter(tl,'.lw',0,{y:-40});}
const old=document.querySelector('.ow');
const cut=b.strike!==undefined?b.strike:.6;
if(old){
  enter(tl,'.ow',.15);
  tl.fromTo('.x',{scaleX:0},{scaleX:1,duration:.3,ease:'power2.out'},cut);
  tl.to('.od',{opacity:.6,duration:.3},cut+.2);
}
const hit=b.slam!==undefined?b.slam:(old?cut+.45:.3);
slam(tl,'.pill',hit,'.w');
if(document.querySelector('.bg')){pop(tl,'.bg',hit+.3,{rotation:-90});}
leave(tl,'.w');
