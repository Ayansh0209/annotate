export type Label = 'Safe' | 'Needs review' | 'Graphic violence' | 'Misleading' | 'Hateful or harassing speech';
export type Page = 'overview' | 'annotate' | 'captions' | 'agreement' | 'judge' | 'guidelines';
export interface Clip { id:string; title:string; type:'video'|'audio'; media_url:string; duration_s:number; source_url:string; licence:string; attribution:string; annotated:boolean; has_caption:boolean; human_scored:boolean }
export interface Study { id:string; title:string; kind:string; total:number; pass1_count:number; pass2_count:number; phase:'pass1'|'waiting'|'pass2'|'complete'; remaining_seconds:number; blind:boolean; ai_configured:boolean; ai_model:string; score_counts:Record<string,number>; configured_delay_minutes:number; delay_minutes:number|null; pass2_available_at:string|null }
export interface Rule { id:string; title:string; text:string }
export interface Guidelines { version:string; labels:Label[]; rules:Rule[]; rubric:Record<string,{title:string;description:string;low:string;high:string}> }
export interface Segment { start_s:number; end_s:number; label:Label }
export interface Score { scorer:'human'|'judge'; accuracy:number; omission:number; hallucination:number; rationale:string; corrected_caption:string; model:string }
export interface CaptionDetail { caption:{caption_text:string; model:string; provenance:string}|null; scores:Score[] }
export interface Difference { id:string; title:string; label1:string; label2:string; rule1:string; rule2:string; rationale1:string; rationale2:string }
export interface Agreement { n:number; agreement_pct:number; kappa:number|null; kappa_note:string|null; labels:string[]; matrix:number[][]; disagreements:Difference[]; flagged:Difference[]; actual_delay_minutes:number; measure:string }
export interface Comparison { n:number; comparisons:number; within_one:number; within_one_pct:number|null; dimensions:Record<string,{pct:number|null;n:number;within_one:number}>; rows:Array<{id:string;title:string;human_rationale:string;judge_rationale:string;[key:string]:string|number}> }
