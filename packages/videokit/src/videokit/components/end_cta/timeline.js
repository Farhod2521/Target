const press=Math.min(1.1,Math.max(.6,P.length-.6));
const tl=gsap.timeline();
enter(tl,'.b',0,{y:120,ease:M.pop});
tl.from('.l2',{opacity:0,y:30,duration:.3,stagger:.1},.25);
tl.fromTo('.cur',{x:160,y:260,opacity:0},{x:0,y:0,opacity:1,duration:.45,ease:'power2.out'},press-.5);
tl.to('.cur',{scale:.85,duration:.08,yoyo:true,repeat:1,transformOrigin:'0 0'},press-.05);
tl.fromTo('.tap',{opacity:0},{opacity:1,duration:.3,ease:'power2.out'},press-.35);
tl.to('.b',{scale:.94,duration:.1,yoyo:true,repeat:1},press);
tl.to('.tap',{scale:1.4,opacity:0,duration:.4},press+.1);
