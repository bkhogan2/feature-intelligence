import {expect,test} from "bun:test";
import {mergeVisible} from "../src/features/opportunities/opportunity-board-model";
test("filtered drag retains hidden cards and persists the visible card's new lifecycle and order",()=>{
 const all=[{id:"a",status:"considering"},{id:"hidden",status:"planned"},{id:"b",status:"shipped"}];
 const moved=[{id:"b",status:"considering"},{id:"a",status:"considering"}];
 expect(mergeVisible(all,moved)).toEqual([moved[0],all[1],moved[1]]);
 expect(all[0]).toEqual({id:"a",status:"considering"});
 expect(all[2]).toEqual({id:"b",status:"shipped"});
});
test("an empty filtered board leaves every record intact",()=>{
 const all=[{id:"a",status:"planned"}];expect(mergeVisible(all,[])).toEqual(all);
});
