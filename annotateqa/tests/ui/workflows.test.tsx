import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import Annotation from '../../src/Annotation';
import Captions from '../../src/Captions';
import { AgreementReport } from '../../src/Reports';
import { UploadModal } from '../../src/components';
import type { Clip, Guidelines, Study } from '../../src/types';

// Isolated component fixtures. Nothing here is saved to the user's database.
const clip:Clip={id:'fixture-one',title:'Test tone',type:'audio',media_url:'/media/fixture-one',duration_s:8,source_url:'Original work',licence:'CC0',attribution:'Test fixture',annotated:false,has_caption:false,human_scored:false};
const state:Study={id:'study',title:'Test study',kind:'study',total:1,pass1_count:0,pass2_count:0,phase:'pass1',remaining_seconds:0,blind:false,ai_configured:false,ai_model:'test',score_counts:{},configured_delay_minutes:60,delay_minutes:null,pass2_available_at:null};
const guidelines:Guidelines={version:'v1',labels:['Safe','Needs review','Graphic violence','Misleading','Hateful or harassing speech'],rules:[{id:'R1',title:'Safe is the default',text:'Use observable evidence.'},{id:'R6',title:'Audio-only',text:'Use the words and sounds, not accents.'},{id:'R8',title:'Unclear',text:'Flag uncertainty.'}],rubric:{accuracy:{title:'Accuracy',description:'Correct details',low:'Incorrect',high:'Correct'},omission:{title:'Completeness (omission)',description:'Missing details',low:'Missing',high:'Complete'},hallucination:{title:'Grounding (hallucination)',description:'Invented details',low:'Invented',high:'Grounded'}}};
let calls:Array<{path:string;body:any}>;
beforeEach(()=>{calls=[];vi.stubGlobal('fetch',vi.fn(async(path:string,options:any={})=>{calls.push({path,body:options.body?JSON.parse(options.body):null});return {ok:true,json:async()=>path.includes('/annotations/')?null:{saved:true}};}));});
afterEach(()=>{cleanup();vi.unstubAllGlobals();});

describe('Annotation interactions',()=>{
 it('requires a label, rule and rationale, and saves timestamped segments',async()=>{
  const refresh=vi.fn(async()=>{});const notify=vi.fn();
  render(<Annotation clips={[clip]} state={state} guidelines={guidelines} refresh={refresh} notify={notify}/>);
  const save=screen.getByRole('button',{name:'Save & next'}) as HTMLButtonElement;
  expect(save.disabled).toBe(true);
  fireEvent.click(screen.getByRole('button',{name:'Safe',exact:true}));
  fireEvent.change(screen.getByLabelText('Guideline rule *'),{target:{value:'R6'}});
  fireEvent.change(screen.getByLabelText('Decision rationale *'),{target:{value:'Only a short tone is audible; no speech is present.'}});
  expect(save.disabled).toBe(false);
  fireEvent.click(screen.getByText('Timestamped segments'));
  fireEvent.change(screen.getByLabelText('End'),{target:{value:'2'}});
  fireEvent.click(screen.getByRole('button',{name:'Add segment'}));
  fireEvent.click(save);
  await waitFor(()=>expect(refresh).toHaveBeenCalledOnce());
  const request=calls.find(c=>c.path==='/api/annotate');
  expect(request?.body).toMatchObject({clip_id:clip.id,pass:1,label:'Safe',rule_id:'R6',segments:[{start_s:0,end_s:2,label:'Safe'}]});
  expect(notify).toHaveBeenCalled();
 });
 it('does not allow starting pass 2 while waiting and reveals no saved labels',()=>{
  render(<Annotation clips={[clip]} state={{...state,phase:'waiting',blind:true,remaining_seconds:300,pass1_count:1}} guidelines={guidelines} refresh={async()=>{}} notify={()=>{}}/>);
  expect((screen.getByRole('button',{name:/Start blind pass 2/}) as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByText('05:00')).toBeTruthy();
  expect(screen.queryByLabelText('Decision rationale *')).toBeNull();
  expect(calls.some(c=>c.path.includes('/annotations/'))).toBe(false);
 });
 it('keeps the agreement endpoint unrequested before completion',()=>{
  render(<AgreementReport state={{...state,phase:'pass2',blind:true,pass1_count:1}}/>);
  expect(screen.getByText('A fair comparison is worth the wait.')).toBeTruthy();
  expect(calls.some(c=>c.path==='/api/agreement')).toBe(false);
 });
});

describe('Caption evaluation interactions',()=>{
 it('requires all three scores and written feedback before committing the human evaluation',async()=>{
  let scored=false;
  const human={scorer:'human',accuracy:5,omission:4,hallucination:5,rationale:'The tone is described accurately, but a pause is omitted.',corrected_caption:'',model:'human'};
  vi.stubGlobal('fetch',vi.fn(async(path:string,options:any={})=>{calls.push({path,body:options.body?JSON.parse(options.body):null});if(path.includes('/scores/'))scored=true;return {ok:true,json:async()=>path.includes('/captions/')?{caption:{caption_text:'A tone is heard.',model:'test fixture',provenance:'unit test'},scores:scored?[human]:[]}:{saved:true}};}));
  render(<Captions clips={[clip]} state={state} guidelines={guidelines} refresh={async()=>{}} notify={()=>{}}/>);
  await screen.findByText('A tone is heard.');
  const save=screen.getByRole('button',{name:'Save my evaluation'}) as HTMLButtonElement;
  expect(save.disabled).toBe(true);
  expect(screen.queryByRole('button',{name:/Run independent judge/})).toBeNull();
  fireEvent.click(screen.getByRole('button',{name:'Accuracy: 5'}));
  fireEvent.click(screen.getByRole('button',{name:'Completeness (omission): 4'}));
  fireEvent.click(screen.getByRole('button',{name:'Grounding (hallucination): 5'}));
  fireEvent.change(screen.getByLabelText('Evidence & feedback *'),{target:{value:human.rationale}});
  fireEvent.click(save);
  await screen.findByText('Your scores are sealed');
  expect(calls.find(c=>c.path==='/api/scores/fixture-one')?.body).toMatchObject({accuracy:5,omission:4,hallucination:5,rationale:human.rationale});
  expect((screen.getByRole('button',{name:/Run independent judge/}) as HTMLButtonElement).disabled).toBe(true);
 });
 it('keeps Gemini unavailable without configuration and does not invent a caption',async()=>{
  vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>({caption:null,scores:[]})})));
  render(<Captions clips={[clip]} state={state} guidelines={guidelines} refresh={async()=>{}} notify={()=>{}}/>);
  await screen.findByText(/Add your Gemini key to .env/);
  const generate=screen.getByRole('button',{name:'Generate caption'}) as HTMLButtonElement;
  expect(generate.disabled).toBe(true);
  fireEvent.click(screen.getByRole('button',{name:'Import a caption'}));
  expect(screen.getByLabelText('Caption text')).toBeTruthy();
  expect((screen.getByRole('button',{name:'Save caption'}) as HTMLButtonElement).disabled).toBe(true);
 });
});
