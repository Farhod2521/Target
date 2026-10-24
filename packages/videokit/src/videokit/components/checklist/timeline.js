const b=P.beats;
const tl=gsap.timeline();
tl.fromTo('.pn',{clipPath:'inset(0 0 100% 0)'},{clipPath:'inset(0 0 0% 0)',duration:.35,ease:M.slide},0);
typeIn(tl,document.querySelector('.tt'),.12,.45);
if(document.querySelector('.pl')){pop(tl,'.pl',.6);}
const rows=[...document.querySelectorAll('.row')];
const said=b.items||[];
const step=Math.min(.7,Math.max(.3,(P.length-1.8)/rows.length));
let at=.7;
rows.forEach((r,i)=>{
  at=Math.max(said[i]!==undefined?said[i]:.9+i*step,at+.2);
  tl.from(r,{x:-120,opacity:0,duration:M.enter,ease:M.slide},at);
  tl.fromTo(r.querySelector('.fl'),{scale:0},{scale:1,duration:.25,ease:'back.out(2)'},at+.25);
  tl.to(r.querySelector('path'),{strokeDashoffset:0,duration:.25,ease:'power2.out'},at+.35);
  tl.fromTo(r,{scale:1},{scale:1.04,duration:.12,yoyo:true,repeat:1},at+.35);
});
tl.to('.pn',{clipPath:'inset(0 0 100% 0)',duration:M.leave,ease:M.leaveEase},P.length-M.leave);
