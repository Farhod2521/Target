const b=P.beats;
const tl=gsap.timeline();
const hit=b.hit!==undefined?b.hit:.1;
tl.fromTo('.st',{scale:2.8,rotation:-14,opacity:0},{scale:1,rotation:-5,opacity:1,duration:.26,ease:'power4.in'},hit);
tl.fromTo('.sw',{x:0,y:0},{x:12,y:-8,duration:.04,yoyo:true,repeat:5,ease:'none'},hit+.26);
const dust=document.querySelector('.dust');
for(let i=0;i<14;i++){
  const d=document.createElement('div');d.className=i%2?'p a':'p';
  const r=10+(i%3)*6;d.style.width=d.style.height=r+'px';dust.appendChild(d);
  const a=i/14*Math.PI*2;
  tl.set(d,{x:-r/2,y:-r/2,opacity:1,scale:1},hit+.26);
  tl.to(d,{x:Math.cos(a)*440,y:Math.sin(a)*160,opacity:0,scale:.3,duration:.6,ease:'power3.out'},hit+.26);
}
if(document.querySelector('.cw')){enter(tl,'.cw',b.rise!==undefined?b.rise:hit+.9,{y:80,ease:M.pop});}
leave(tl,['.sw','.cw']);
