const b=P.beats;
const tl=gsap.timeline();
tl.fromTo('.pn',{clipPath:'inset(0 0 100% 0)'},{clipPath:'inset(0 0 0% 0)',duration:.35,ease:M.slide},0);
tl.from('.ph',{y:260,rotation:-8,opacity:0,duration:.55,ease:'back.out(1.4)'},.08);
enter(tl,'.ti',.2,{x:60,y:0});
if(document.querySelector('.ai')){tl.fromTo('.ai',{scale:1},{scale:1.08,duration:.6,yoyo:true,repeat:5,ease:'sine.inOut'},.6);}
const chips=[...document.querySelectorAll('.chip')];
const said=b.chips||[];
let at=.3;
chips.forEach((c,i)=>{at=Math.max(said[i]!==undefined?said[i]:.55+i*.3,at+.15);pop(tl,c,at,{transformOrigin:'0% 50%'});});
const row=document.querySelector('.tr');
if(row){
  enter(tl,row,at+.4,{x:60,y:0});
  const on=Math.max(b.switch!==undefined?b.switch:at+1.3,at+.9);
  const sw=row.querySelector('.sw').getBoundingClientRect();
  const cur=document.querySelector('.cur').style,rp=document.querySelector('.rp').style;
  cur.left=(sw.left+112)+'px';cur.top=(sw.top+100)+'px';
  rp.left=(sw.left+57)+'px';rp.top=(sw.top+3)+'px';
  tl.fromTo('.cur',{x:240,y:180,opacity:0},{x:-30,y:-70,opacity:1,duration:.45,ease:'power2.out'},on-.5);
  tl.to('.cur',{scale:.85,duration:.08,yoyo:true,repeat:1,transformOrigin:'0 0'},on-.05);
  burst(tl,'.rp',on);
  tl.to('.kn',{x:54,duration:.22,ease:'power2.out'},on);
  tl.to('.on',{opacity:1,duration:.22},on);
  tl.to('.cur',{opacity:0,duration:.25},on+.5);
  if(document.querySelector('.bw')){pop(tl,'.bw',on+.3,{y:40,transformOrigin:'0% 50%'});}
  tl.to('.lk2',{opacity:1,duration:.1},on+.35);
  const h=document.querySelector('.hearts');
  for(let i=0;i<9;i++){
    const e=document.createElement('i');const s=40+(i%3)*12;
    e.style.cssText='left:'+(110+(i%3)*24)+'px;top:820px;width:'+s+'px;height:'+s+'px';
    e.innerHTML=document.querySelector('.lk2').innerHTML;h.appendChild(e);
    const t=on+.4+i*.09;
    tl.set(e,{opacity:1,scale:.3,x:0,y:0},t);
    tl.to(e,{y:-320-(i%4)*60,x:(i%2?1:-1)*(30+i*8),scale:1,duration:.9,ease:'power1.out'},t);
    tl.to(e,{opacity:0,duration:.3},t+.65);
  }
}
tl.to('.pn',{clipPath:'inset(0 0 100% 0)',duration:M.leave,ease:M.leaveEase},P.length-M.leave);
