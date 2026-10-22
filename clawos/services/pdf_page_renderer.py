"""Bounded PDF page rendering with real page geometry and selectable text."""
from pathlib import Path
import base64
import threading
from collections import OrderedDict

class PdfPageRenderer:
    def __init__(self):
        self.cache=OrderedDict();self.lock=threading.RLock()
    def render(self,path,page=1):
        import fitz
        source=Path(path).resolve()
        if source.suffix.lower()!='.pdf':raise ValueError('仅 PDF 支持按页阅读')
        stat=source.stat()
        if stat.st_size>50*1024*1024:raise ValueError('PDF 需小于 50 MB')
        key=(str(source),stat.st_mtime_ns,stat.st_size,page)
        with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key);return self.cache[key]
        with fitz.open(source) as pdf:
            if pdf.needs_pass:raise ValueError('请先在本地解密 PDF，再导入')
            if type(page) is not int or not 1<=page<=len(pdf):raise ValueError('页码超出文献范围')
            p=pdf[page-1];w,h=p.rect.width,p.rect.height
            if w<=0 or h<=0 or w*h>4000000:raise ValueError('PDF 页面尺寸过大，无法安全预览')
            scale=min(1.5,1800/max(w,h))
            pix=p.get_pixmap(matrix=fitz.Matrix(scale,scale),alpha=False)
            lines=[]
            for b in (p.get_text('dict')['blocks'] if p.rotation==0 else []):
                for line in b.get('lines',[]):
                    for span in line.get('spans',[]):
                        x0,y0,x1,y1=span['bbox']
                        text=span['text']
                        if text:lines.append(dict(text=text,x=max(0,x0/w),y=max(0,y0/h),width=max(.001,(x1-x0)/w),height=max(.001,(y1-y0)/h),size=span['size']/w))
            value=dict(page=page,pages=len(pdf),width=w,height=h,image='data:image/png;base64,'+base64.b64encode(pix.tobytes('png')).decode(),
                text=lines,toc=[dict(level=r[0],title=r[1][:200],page=r[2]) for r in pdf.get_toc() if 1<=r[2]<=len(pdf)][:200],
                boundary='原始 PDF 当前页；文字层用于选择，原图用于核对。扫描页无文字层时仍显示原图。')
        if source.stat().st_mtime_ns!=stat.st_mtime_ns:raise ValueError('原文件在渲染期间发生变化，请重新打开')
        with self.lock:
            self.cache[key]=value
            while len(self.cache)>8:self.cache.popitem(last=False)
        return value
