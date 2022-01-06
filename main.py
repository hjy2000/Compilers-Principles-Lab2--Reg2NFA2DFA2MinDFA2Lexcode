# -*- coding: utf-8 -*-
import pandas as pd
from tkinter.constants import END
from pythonds.basic import Stack
from tkinter import *
import tkinter as tk
import matplotlib.pyplot as plt
import numpy as np
from tkinter import _flatten
from tkinter import ttk
from tkinter.filedialog import askopenfilename
from tkinter import messagebox


# ~号即为epsilon
#operatorList={'|','*','(',')','.'}#运算符
class nfaState:#定义NFA状态
    def __init__(self,stateInput='#',index=0,stateType=0,stateNext=-1,epTrans=[]):
        self.stateInput=stateInput
        self.index=index
        self.stateType=stateType#默认为0 即为普通状态 1为start 2为end
        self.stateNext=stateNext
        self.epTrans=epTrans
        
class NFA:
    def __init__(self,head="",tail=""):
        self.head=head
        self.tail=tail
        
class edge:#定义DFA的转换弧
    def __init__(self,edgeInput='#',edgeNext=-1):
        self.edgeName=edgeInput#弧上的值
        self.edgeNext=edgeNext#弧所指向的状态号
'''
class dfaState:#定义DFA状态
    def __init__(self,isEnd=False,index=0,closure=[],edgeNum=0,edges=[]):
        self.isEnd=isEnd
        self.index=index
        self.clousure=closure
        self.edgeNum=edgeNum
        self.edges=edges
        
class DFA:
    def __init__(self,startState=0,endStates=[],terminator=[],trans=[]):
        self.startState=startState
        self.endStates=endStates
        self.terminator=terminator
        self.trans=trans
'''

def add(s1,s2,ch):#在两个nfaState之间生成一条从前一个状态指向后一个状态的弧
    if ch=='~':
        s1.epTrans.append(s2.index)
        s1.stateInput='~'
        #s1.stateNext=s2.index
    else:
        s1.stateInput=ch
        s1.stateNext=s2.index
        
def createNFA(total):
    global nfaStates
    n=NFA()
    n.head=nfaStates[total]
    n.tail=nfaStates[total+1]
    n.head.stateType=1
    n.tail.stateType=2
    return n

def str2NFA(reList):
    global nfaStateNum
    global nfaStates
    nfaStack=Stack()
    length=len(reList)
    for i in range(length):
        if reList[i]>='a' and reList[i]<='z':
            n=createNFA(nfaStateNum)
            nfaStateNum+=2
            add(n.head,n.tail,reList[i])
            nfaStack.push(n)
            
        elif reList[i]=='*':
            n1=createNFA(nfaStateNum)
            nfaStateNum += 2;
            n2=nfaStack.peek()
            nfaStack.pop()
            
            add(n2.tail,n1.head,'~')
            add(n2.tail,n1.tail,'~')#疑问
            add(n1.head,n2.head,'~')
            add(n1.head,n1.tail,'~')
            n.head.stateType=1
            n.tail.stateType=2
            nfaStack.push(n1)
            
        elif reList[i]=='|':
            
            n2=nfaStack.peek()
            nfaStack.pop()
            n1=nfaStack.peek()
            nfaStack.pop()
            n=createNFA(nfaStateNum)
            
            nfaStateNum+=2
            temp=nfaStateNum
            
            add(n.head,n1.head,'~')
            add(n.head,n2.head,'~')
            add(n1.tail,n.tail,'~')
            add(n2.tail,n.tail,'~')
            n.head.stateType=1
            n.tail.stateType=2
            #print(n.head.index)
            #n.head.index=0
            #print(n.head.index)
            
            #print(n.tail.epTrans)
            #for k in range(len(nfaStates[temp-1].epTrans)):
                #nfaStates[temp-1].epTrans[k]+=1
                
            '''
            print(n.head.epTrans)
            for j in range(temp-1):
                nfaStates[j].index+=1
                if nfaStates[j].epTrans==[]:
                    nfaStates[j].stateNext+=1
                else:
                    for data in nfaStates[j].epTrans:
                        data+=1
                
            
            #更新状态函数要完整实现
            '''
            nfaStack.push(n)
            
        elif reList[i]=='.':
            n2=nfaStack.peek()
            nfaStack.pop()
            n1=nfaStack.peek()
            nfaStack.pop()
            n=NFA()
            add(n1.tail,n2.head,'~')
            n.head=n1.head
            n.tail=n2.tail
            n.head.stateType=1
            n.tail.stateType=2
            #n1.head.stateType=0
            n2.head.stateType=0
            n1.tail.stateType=0
            #n2.tail.stateType=0
            
            nfaStack.push(n)
        else:
            raise RuntimeError("表达式有误")
    return nfaStack.peek()
        
def add_symbols(reList):#添加连接符'.'
    length=len(reList)#正则表达式长度
    j=0
    for i in range(length-1):
        
        if reList[i+j]==')' or  reList[i+j]=='*' or reList[i+j].isalpha()==True:
            if reList[i+1+j]=='(' or reList[i+1+j].isalnum()==True:
                reList.insert(i+j+1,'.')
                j+=1
    return reList

def getN(operator):#返回运算符编号
    N={
       
       '#':0,
       '|':1,
       '.':2,
       '*':3,
       '(':4,
       ')':5
       
       }
    return N.get(operator,None)

#print(getN('#')) testpoint

def convert_operators(reList):
    length=len(reList)
    global priorities
    post=[]
    s=Stack()#创建符号栈
    #print(s.isEmpty())
    s.push('#') #预置栈底元素#
    
    for i in range(length):
        if reList[i].isalnum()==True:
            post.append(reList[i])
        else:
            if getN(reList[i])==4:
                s.push(reList[i])
                #break
            elif getN(reList[i])==5:
                while s.isEmpty()==False and s.peek()!='(':
                    post.append(s.peek())
                    s.pop()
                s.pop()
                #break
            else:
                if (s.peek()=='(') or (s.peek()!='(' and priorities[getN(s.peek())][getN(reList[i])]=='<'):
                    s.push(reList[i])
                else:
                    while(priorities[getN(s.peek())][getN(reList[i])]=='>'):
                        post.append(s.peek())
                        s.pop()
                    s.push(reList[i])
                #break
            
    while s.isEmpty()==False:
        post.append(s.peek())
        s.pop()
    post.pop()#删掉预置的#
    #print(post)
    return post
#NFA2DFA


def epClosure(i):#求nfaStates中的第i项的ep闭包
    global nfaStates
    global nfaStateNum
    epStack=Stack()
    
    #for i in range(nfaStateNum):
        #if nfaStates[i].stateInput=='~':
    ep=[]
            #str1='nfa结点index:为'+str(i)+'的ep闭包为：'
    ep.append(i)
    epStack.push(i)
        
    while(epStack.isEmpty()==False):
            
        top=epStack.pop()#闭包完毕后仍然会pop所以最后栈空结束while
        if isinstance(top,list)!=True:
            for i in range(len(nfaStates[top].epTrans)):
                if nfaStates[top].epTrans[i] not in ep:
                    ep.append(nfaStates[top].epTrans[i])
                    epStack.push(nfaStates[top].epTrans[i])
                    
                    
    #epChart.append(ep)
    return ep


def aftertrans_epClosure(s,word):#求单个状态集的ε-cloure(move(ch)) 即通过终结符边后再求边到达的节点的ep闭包
    global nfaStates
    global nfaStateNum
    global endStates
    global start
    #global wordsChart
    
    for i in range(nfaStateNum):#遍历求当前的start状态和end状态所在的下标
        if nfaStates[i].stateType==1:
            start=i
            #print(start)
        if nfaStates[i].stateType==2 and nfaStates[i].index not in endStates:
            endStates.append(i)#终态集
            #print(end)
            
    if s=='s':
        s=start
        
    A=epClosure(s)#求集的ep闭包并将其设为A
    #fList=[]
    #for word in wordsChart:
    wordsEp=[]
    for data in A:
        if isinstance(data,list)!=True:
            if nfaStates[data].stateInput==word:
                wordsEp.append(nfaStates[data].stateNext)
            
    wordsEp1=[]
    for datum in wordsEp:
        ee=epClosure(datum)
        #print('test'+str(ee))
        for num in range(len(ee)):
            wordsEp1.append(ee[num])
    #fList.append(wordsEp1)
    #print(fList)
    #print('test1111')
    #print(wordsEp1)
    return wordsEp1
        
#print(aftertrans_epClosure('s','a'))
            
#print()

def nfa2DFA():
    global produced_reList
    global wordsChart
    global start
    global endStates
    global nfaStateNum
    dfaStates=[]#dfa状态列表
    dfaStack=Stack()#dfa栈
    tag=1
    for num in range(len(wordsChart)):
        d=aftertrans_epClosure('s',wordsChart[num])#求初始状态的move(A,a)ep闭包
        dd=epClosure(start)
        dfaStates.append(dd)
        dfaStates.append(d)
        dfaStack.push(d)#这里d即为初状态的move(A,a)ep闭包
        while(dfaStack.isEmpty()==False):
            top=dfaStack.pop()#完毕后仍然会pop所以最后栈空结束while
            if top!=dfaStates[tag] or tag==1:
                for item in top:
                    iiList=[]
                    if num < len(wordsChart)-1:
                        d=aftertrans_epClosure(item,wordsChart[num+1])
                        for ii in d:
                            if ii not in iiList:
                                iiList.append(d)
                        
                        dfaStates.append(iiList)
                        dfaStack.push(iiList)
                        tag+=1
                #print(wordsChart[num])
                #print()
                    #dfaStack.push(d)#这里d即为初状态的move(A,a)ep闭包
                    #dfaStates.append(d)
    return dfaStates
                
#print(nfa2DFA())



def dfaStatesCount():#计算DFA状态数
    global start
    global dfaList
    dfaStates=nfa2DFA()
    dd=epClosure(start)
    dfaList.append(dd)
    count=1
    dd=epClosure(start)
    for i in range(len(dfaStates)):
        if dfaStates[i]!=[] and dfaStates[i]!=dd and dfaStates[i]!=dfaStates[i-1]:
            #if 
            count+=1
            dfaList.append(dfaStates[i])
            
    return count


stateWord='A'
dfaStatusChart = pd.DataFrame(np.zeros((dfaStatesCount()+1,2+len(wordsChart)),dtype=str))#构建DFA转换表
dfaStatusChart.iloc[0,0]='NFA状态集'
dfaStatusChart.iloc[0,1]='DFA状态号'
#dfaStatesCount()

def dfaChart():#初始化DFA状态转换表
    global stateWord
    global dfaList
    global dfaStatusChart
    dfaL=[]
    for i in range(dfaStatesCount()):
        string1=""
        dfaL=[]
        for item in dfaList[i]:
            
            #print('dfastates')
            #print(dfaList[i])
            #print()
            if isinstance(item,list)!=True:
                
                #print('not list')
                string1+=str(item)+" "
                dfaL.append(item)
                #print(string1)
            else:
                string1=""
                dfaL=[]
                #print('list')
                #item=tuple(item)
                #print('tuple')
                #print(item)
                for itemm in item:
                    dfaL=[]
                    if isinstance(itemm,list)!=True:#判断是否为列表
                        dfaL=[]
                        #print(type(itemm))
                        #print('not list111')
                        string1+=str(itemm)+" "
                        dfaL.append(item)
                    else:
                        
                        dfaL=list(_flatten(dfaL))
                        print(list(_flatten(dfaL)))
                            
                dfaL=list(_flatten(dfaL))#列表去重
                #print(list(_flatten(dfaL)))
            #print(string)
            
        dfaStatusChart.iloc[i+1,0]=dfaL
        dfaStatusChart.iloc[i+1,1]=stateWord
        
        stateWord=chr((ord(stateWord))+1)
    
        #print('字母'+stateWord)
    for i in range(len(wordsChart)):
        dfaStatusChart.iloc[0,2+i]=wordsChart[i]
    
    
    return dfaStatusChart

def dfaChartInsert():#dfaList去重并插入dfa状态的边的情况
    global dfaStatusChart
    global wordsChart
    global endStates
    chartStatus=[]
    for data in dfaStatusChart.iloc[1:,0]:
        chartStatus.append(data)
    
    #print(chartStatus)
    for i in range(len(chartStatus)-1):
        for k in range(len(chartStatus[i])):
            for j in range(len(wordsChart)):
                aep=aftertrans_epClosure(chartStatus[i][k],wordsChart[j])
                #print(chartStatus[i][k])
                if aep==chartStatus[i+1]:
                    #print('aep')
                    #print(aep)
                    #if dfaStatusChart.iloc[]chartStatus[i+1]
                    dfaStatusChart.iloc[i+1,2+j]=dfaStatusChart.iloc[i+2,1]
        
    for i in range(len(chartStatus)):
        for k in range(len(chartStatus[i])):
            #print(chartStatus[i])
            for j in range(len(wordsChart)):
                #print(wordsChart[j])
                aep1=aftertrans_epClosure(chartStatus[i][k],wordsChart[j])
                #print('aep1')
                #print(aep1)
                if aep1==chartStatus[-1]:
                    dfaStatusChart.iloc[i+1,2+j]=dfaStatusChart.iloc[-1,1]
            
    
    dfaStatusChart.insert(2+len(wordsChart),'',0)
    dfaStatusChart.iloc[0,2+len(wordsChart)]="stateType"#新增是否为终态或者不可达及不可到达终态的标志
    #普通状态均初始化为0,1为终态，2为不可达状态，3为不可到达终态的情况
    
    for i in range(len(chartStatus)):#在这里先确定DFA中的终态
        for j in range(len(wordsChart)):
            #print(list(set(aep) & set(endStates)))
            if list(set(chartStatus[i]) & set(endStates))!=[]:
                dfaStatusChart.iloc[i+1,-1]=1
                
#print(aftertrans_epClosure(6, 'c'))

#DFA最小化
def checkStatus():#检查是否不可达或者不可到达终态
    global dfaStatusChart

def minDFA():
    checkStatus()
    
#生成词法分析程序
#import copy
stringCode ="int count=0;\nint main()\n{\nif(ch >= 'a' && ch <='z')\n{"

def genAnd(chList):
    global stringCode
    global dfaStatusChart
    global wordsChart
    for i in range(len(chList)):
        #ch=chList[i].lower()
        for j in range(len((dfaStatusChart))):
            for k in range(len(dfaStatusChart)):
                pass
            
        stringCode+="\nif(ch=='"+chList[i].lower()+"')\n{count+=1;\n"
def genCode():
    global dfaStatusChart
    global wordsChart
    global stringCode
    chartStatus=[]
    for data in dfaStatusChart.iloc[1:,0]:
        chartStatus.append(data)
    
    orList=[]
    for i in range(len(chartStatus)):
        count=0
        tempList=[]
        for j in range(2,2+len(wordsChart)):
            if dfaStatusChart.iloc[i+1,j]>='A' and dfaStatusChart.iloc[i+1,j]<='Z':
                #print(1)
                
                tempList.append(dfaStatusChart.iloc[i+1,j])
                count+=1
                
        if count>1:
            genAnd(tempList)
            
        orList.append(tempList)
        
    print(orList)
    
def show_nfaChart():
    #run()
    global nfaStatusChart
    for i in range(len(nfaStatusChart)):
        print(list(nfaStatusChart[i]))
        TV1.insert('','end',iid=None,text=nfaStatusChart[i],values="")
    TV1.grid(row=2,column=1)
        
        
def show_dfaChart():
    global dfaStatusChart
    chart=np.array(dfaStatusChart)
    
    for i in range(dfaStatesCount()+1):
        '''
        tempList=[]
        for item in dfaStatusChart[i]:
            tempList.append(item)
        print(tempList)
            '''
        #print(dfaStatusChart.iloc[i,:])
        
        TV1.insert('','end',text=chart[i],values="")
    TV1.grid(row=2,column=1)

def show_minDfaChart():
    pass

def show_Code():
    genCode()
    print(stringCode)
    messagebox.showinfo('词法分析程序',stringCode,parent=window)

def openRegFile():
    global re
    file_path=askopenfilename(title="打开文本文件",filetypes=[('TXT', '*.txt')])
    with open(file_path,encoding='utf-8') as f:
        if f==-1:
            messagebox.showerror('showerror', 'hello', parent=window)
            
        line = f.readline()
        print(line)
        setTextInput(line)
        
def show_Info():
    messagebox.showinfo('版本信息', '2018213055 侯佳耀 Xlex分析器 V1.0', parent=window)
    
def setTextInput(text):
    E1.delete(0,"end")
    E1.insert(0, text)

if __name__ == '__main__':
    
    
    nfaStateNum=0
    nfaStates=[]
    MAX=64

    for i in range(MAX):#初始化
        n=nfaState('#',i,0,-1,[])
        nfaStates.append(n)

    reList=[]
    re="a*"
    print(re)
    
    for letter in re:
        reList.append(letter)
    produced_reList=convert_operators(add_symbols(reList))
    #print(produced_reList)
    #print()

    nfa=str2NFA(produced_reList)
    #print(nfa.tail.index)
    #print(nfa.head.epTrans)
    #print()
    nfaStatusChart = np.zeros((nfa.tail.index+1,nfa.tail.index+1),dtype=str)#NFA状态转换表

    for i in range(nfaStateNum):
        if nfaStates[i].stateInput!='#' and nfaStates[i].epTrans==[]:
            
            nfaStatusChart[nfaStates[i].index][nfaStates[i].stateNext]=nfaStates[i].stateInput
        elif nfaStates[i].epTrans!=[]:
            for data in nfaStates[i].epTrans:
                nfaStatusChart[nfaStates[i].index][data]=nfaStates[i].stateInput

    #print(nfaStatusChart)

    #构建基本字母表
    wordsChart=[]
    for i in range(nfaStateNum):
        if nfaStates[i].stateInput>='a' and nfaStates[i].stateInput<='z':
            wordsChart.append(nfaStates[i].stateInput)
            
    epChart=[]

    #epppp=epClosure(4)
    endStates=[]
    start=-1
    dfaList=[]

    priorities=[
        #运算符优先级表 #|.*()
        "E<<<<X",
        ">><<<>",
        ">>><<>",
        ">>>><>",
        "x<<<<=",
        "xxxxxx",]
        
    dfaChart()
    dfaChartInsert()
    genCode()
    print(stringCode)
    
    window=tk.Tk()
    window.title('Xlex')
    window.geometry('960x800')
    e = StringVar()
    E1=tk.Entry(window,width=30,bd=10,textvariable=e)
    e.set('abc')
    E1.grid(row=1,column=1)
    
    btnOpenfile=tk.Button(window,text='打开文件',height = 2,width = 10,command=openRegFile)
    btnOpenfile.grid(row=1,column=2)
    
    B1=tk.Button(window,text='表达式转NFA',height = 2,width = 10,command=show_nfaChart)
    B1.grid(row=1,column=3)
    
    B2=tk.Button(window,text='NFA转DFA',height = 2,width = 10,command=show_dfaChart)
    B2.grid(row=1,column=4)
    
    B3=tk.Button(window,text='DFA最小化',height = 2,width = 10,command=show_dfaChart)
    B3.grid(row=1,column=5)
    
    B4=tk.Button(window,text="生成词法分析程序",height = 2,width = 15,command=show_Code)
    B4.grid(row=1,column=6)
    
    B5=tk.Button(window,text="关于",height = 2,width = 10,command=show_Info)
    B5.grid(row=1,column=7)
    
    TV1=ttk.Treeview(window)
    TV1.grid(row=2,column=1)
    
    window.mainloop()
    
    
    
    
