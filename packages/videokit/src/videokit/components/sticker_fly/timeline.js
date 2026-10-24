const tl=gsap.timeline();
const k=document.querySelector('.k');
const flies=/^(rocket|arrow)$/.test(k.dataset.icon);
const d=P.length;
const at=t=>flies?[-200+1300*Math.pow(t,1.6),380-420*Math.pow(t,1.6)]:[440+120*Math.sin(t*Math.PI*2),420-520*t];
const [x0,y0]=at(0),[x1,y1]=at(1);
if(flies){
  tl.fromTo(k,{x:x0,y:y0,rotation:k.dataset.icon==='arrow'?-25:0},{x:x1,y:y1,duration:d,ease:'power1.in'},0);
}else{
  const o={t:0};
  tl.fromTo(k,{x:x0,y:y0,scale:.4,opacity:0},{scale:1,opacity:1,duration:.25,ease:'back.out(2)'},0);
  tl.to(o,{t:1,duration:d,ease:'none',onUpdate:()=>{const p=at(o.t);gsap.set(k,{x:p[0],y:p[1]});}},0);
  tl.to(k,{opacity:0,duration:.25},d-.25);
}
const trail=document.querySelector('.tr');
for(let i=0;i<12;i++){
  const e=document.createElement('div');e.className='d';const r=26-i;
  e.style.width=e.style.height=r+'px';trail.appendChild(e);
  const t=i/14,p=at(t);
  tl.set(e,{x:p[0]+90,y:p[1]+150,opacity:.8,scale:1},t*d);
  tl.to(e,{opacity:0,scale:2.2,duration:.6},t*d);
}
