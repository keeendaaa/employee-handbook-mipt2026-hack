import {it,expect} from 'vitest';
import {graphLayout} from './graph';
it('keeps all 1–32 topic nodes inside the graph without overlap',()=>{
 for(let count=1;count<=32;count++)for(const width of [320,744,1056]){
  const layout=graphLayout(Array.from({length:count},(_,i)=>String(i)),10,width),nodes=[...layout.centres.values()];
  for(const a of nodes){expect(a.x-106).toBeGreaterThanOrEqual(0);expect(a.x+106).toBeLessThanOrEqual(layout.width-300);expect(a.y-32).toBeGreaterThanOrEqual(0);expect(a.y+46).toBeLessThanOrEqual(layout.height);}
  for(let i=0;i<nodes.length;i++)for(let j=i+1;j<nodes.length;j++)expect(Math.abs(nodes[i].x-nodes[j].x)>=212||Math.abs(nodes[i].y-nodes[j].y)>=78).toBe(true);
 }
});
