const tl=gsap.timeline();
const w=P.beats.shows;
if(w){
  tl.set('.c',{opacity:0},0);
  for(let i=0;i+1<w.length;i+=2){
    tl.to('.c',{opacity:.85,duration:.3},w[i]);
    tl.to('.c',{opacity:0,duration:.3},Math.max(w[i]+.3,w[i+1]-.3));
  }
}else{
  tl.from('.c',{opacity:0,duration:.3},0);
  tl.to('.c',{opacity:0,duration:.3},Math.max(.3,P.length-.3));
}
