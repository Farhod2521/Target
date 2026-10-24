const tl=gsap.timeline();
tl.from('.p',{yPercent:-100,duration:M.enter,ease:M.slide},0);
tl.from('.h',{opacity:0,y:30,duration:.35},.25);
const step=Math.min(.45,Math.max(.2,(P.length-1.4)/P.items.length));
const said=P.beats.items||[];
let at=.45;
document.querySelectorAll('.chip').forEach((c,i)=>{
  at=Math.max(said[i]!==undefined?said[i]:.6+i*step,at+.15);
  pop(tl,c,at,{x:-80,scale:.8});
});
tl.to('.p',{yPercent:-100,duration:M.leave,ease:M.leaveEase},P.length-M.leave);
