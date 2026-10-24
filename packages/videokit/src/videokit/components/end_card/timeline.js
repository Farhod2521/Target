const mark=document.querySelector('.logo').getBoundingClientRect();
const ring=document.querySelector('.rg');
const across=Math.max(mark.width,mark.height)+120;
const tl=gsap.timeline();
tl.fromTo('.e',{opacity:0,scale:1.08},{opacity:1,scale:1,duration:.3,ease:'power2.out'},0);
if(across<=820){
  ring.setAttribute('width',across);ring.setAttribute('height',across);
  document.querySelector('.rl').style.strokeWidth=14*800/across;
  ring.style.left=(mark.left+mark.width/2-across/2)+'px';ring.style.top=(mark.top+mark.height/2-across/2)+'px';
  tl.to('.rl',{strokeDashoffset:0,duration:.8,ease:'power3.out'},.1);
}else{ring.style.display='none';}
pop(tl,'.logo',.1,{rotation:-25});
tl.from('.n',{opacity:0,y:40,duration:.35},.4);
tl.from('.s',{opacity:0,y:30,duration:.35},.55);
