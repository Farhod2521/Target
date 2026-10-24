if(P.label){document.querySelectorAll('.own').forEach(e=>e.remove());}
const press=Math.min(1.1,Math.max(.6,P.length-.6));
const tl=gsap.timeline();
enter(tl,'.b',0,{y:150,ease:M.pop});
tl.fromTo('.tap',{opacity:0},{opacity:1,duration:.3,ease:'power2.out'},press-.35);
tl.to('.b',{scale:.92,duration:.1,yoyo:true,repeat:1},press);
tl.to('.tap',{scale:1.4,opacity:0,duration:.4},press+.1);
tl.to('.b',{opacity:0,y:40,duration:M.leave,ease:M.leaveEase},P.length-M.leave);
