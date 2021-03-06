#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Sep  8 14:35:58 2017

@author: Jonathan Peters
"""


import numpy as np
import matplotlib.pyplot as plt
import cplex
import scipy.sparse as ss
import time


#%%
#Vehicle routing with delivery windows and linear time dependence.
class RTSPSubproblem(object):
    def __init__(self,  DeliveryWindows,travel_times, Time_Windows, params, startTime, fixedStart = False):
        #nnodes should be an integer, equal to the number of customers, plus one more for the depot.
        #Timewindows should be a matrix with nnodes rows and 2 columns. For a given row, the two values in the matrix refer to the time after which the delivery may be made, and the time before which the delivery must be made.
        
        if np.size(DeliveryWindows,0)!= params[0]:
            raise ValueError("Invalid input, there should be a time window for each customer, and for the depot itself")
            
        if np.size(travel_times, 0)!= params[0]:
            raise ValueError("Invalid input, the first and 2nd dimensional lengths of the travel time tensor should equal the number of nodes")

        self.n, self.service_time, self.start, self.end, self.alpha, self.tightness = params

        #record the delivery windows for each node
        self.DW = DeliveryWindows;
        
        #record the number of time windows which exist
        self.K = np.size(Time_Windows) - 1       
        
        #Record the times of the day when travel times change. That is, between self.TW[j] and self.TW[j+1] one framework applies. However, after self.TW[j], then the rules changes. Overall, travel times must be piecewise linear though, so things don't change too much.
        self.Theta = Time_Windows
        
        #We introduce a dummy variable chi_{i,k} which implies that node i is departed during time slot k. Due to Delivery Windows, certain values of chi are restricted in advance, similar to how certain edges are restricted in advance. We record the list of chi's which might take a value of 1, ignoring the others which are restricted to 0.
        self.departureSlots = self.ImportantDepartureSlots()
        
        #record the number of possible chi's which exist. 
        self.kappa = len(self.slots)        
        
        #identify the edges which might be used, and ignore the others.
        self.edges = self.ImportantEdges(travel_times)
        
        #record the number of possible edges
        self.m = np.size(self.edges, 0)
        
        #a big number
        self.M = 100000
        
        self.prep() 
        
        #one variable for each edges, one service time commencement variable for each node, one waiting time variable for each node, one regret variable for each node, one decision variable for each edge x travel time window indicating during which such window is that node departed from
        self.nvars = 2*self.m+self.n + self.kappa+1
        self.neqcons = 3*(self.n-1)
        self.nineqcons = self.m + self.K2 + 3*(self.n)-3
        self.ncons = self.neqcons + self.nineqcons
        
        #record the matrix of refined travel times (tt for short), such that tt[e,k] refers to the time taken to travel along edge 'e' at time change point Theta[k]
        self.tt = np.array([travel_times[self.edges[i][0], self.edges[i][1], :] for i in range(self.m)])
        
        timeobj = [0]*self.n
        timeobj[self.start] = -tuning_params[1]
        timeobj[self.end] = 1
        
        self.obj =[0]*(2*self.m+self.kappa)+timeobj +[self.alpha]

    
    def indexSlotMap(self, i,j,k):
        return self.ijk_to_ind[k][i,j]-1
    
    def indexMap(self, i,j):
        return int(self.ij_to_e[i,j]-1)

    def slotMap(self, i,j):
        return self.slotInv[i,j] -1
    
    def prep(self):
        self.combos = [[ii,jj, kk] for ii in range(self.n) for jj in self.outSet[ii] for kk in self.departureSlots[ii]]
        self.K2 = len(self.combos)
        
        
        temp = np.zeros([self.n, self.n, self.K])
        
        count = 1
        for i in self.combos:
            temp[i[0], i[1], i[2] ]= count
            count +=1
        
        self.ijk_to_ind = [[] for _ in range(self.K)]
        for k in range(self.K):
            self.ijk_to_ind[k] = ss.csc_matrix(temp[:, :,k], dtype=int)
    
    def ImportantDepartureSlots(self):
        possibilities = [[] for i in range(self.n)]
        
        for i in range(0,self.n):
            if i!= self.end:
                arr = [j for j in self.DW[i, 0]-self.Theta ]
                valmin = np.min([j for j in arr if j>0])
                kmin = arr.index(valmin)
                
                arr = [j for j in self.Theta -self.tightness-self.service_time- self.DW[i,1]]
                valmax = np.min([j for j in arr if j >0])
                kmax = arr.index(valmax)
                
                possibilities[i]=[j for j in range(kmin,kmax)]
        
        self.slots = []
        for i in range(self.n):
            for j in possibilities[i]:
                self.slots.append([i,j])
        
        slotInv = np.zeros([self.n, self.K])
        count = 1;
        for slot in self.slots:
            slotInv[slot[0], slot[1]] = count;
            count+=1
        
        self.slotInv = ss.csc_matrix(slotInv, dtype=int)

        
        return possibilities
        
    def ImportantEdges(self, travel_times):
       #This function takes the complete graph with 'nnodes' nodes, and refines it to the important edges. For example if TW[i,2]<TW[j,1], then the edge from j to i is redundant and can be ignored.
       edges = []
       
       self.inSet = [[] for _ in range(self.n)]
       self.outSet = [[] for _ in range(self.n)]
       
       ij_to_e = np.zeros([self.n, self.n])
       
       
       #Full_Set = sets.Set([i for i in range(self.nnodes)])
       
       Ordering= [[set([]) for _ in range(3)] for _ in range(self.n)]
       
       
       #This loop figues out the basic ordering hierarchy
       
       for node in range(self.n):
           
           for other in range(self.n):
               if(node!=other and node != self.start and node !=self.end):
                   if node != self.end :
                       tmp = np.min([travel_times[node, other,k] for k in self.departureSlots[node]])
                       #tmp2 = np.min([travel_times[other,node,k] for k in self.departureSlots[other]])
                       
                       if self.DW[node, 0]+ tmp> self.DW[other,1]+self.tightness:
                           Ordering[node][0].add(other)
                       #elif self.DW[other,0]+tmp2> self.DW[node,1]+self.tolerable_lateness:
                       #    Ordering[node][2].add(other)
                       else:
                           Ordering[node][1].add(other)
                
       for i in range(self.n):
           if i!= self.start and i!= self.end:
               Ordering[self.start][2].add(i)
               Ordering[i][0].add(self.start)
               Ordering[i][1].remove(self.start)
               
               Ordering[self.end][0].add(i)
               Ordering[i][2].add(self.end)
               Ordering[i][1].remove(self.end)

        
       #This loop completes the hierarchy procedure by identifying which nodes
       #are 'much' greater in the hierarchy than others.

       for node in range(self.n):
           
           for between in list(Ordering[node][2]):
               
               for outside in list(Ordering[between][2]):
                   if outside in Ordering[node][2]:
                       #Ordering[node][4].add(outside)
                       Ordering[node][2].remove(outside);
                       #Ordering[outside][0].add(node);
                       Ordering[outside][0].remove(node)
       
       #Finally we need to sort out the unique status of the depot in the hierarchy.
       
       
       count = 0;
       for i in range(self.n):
           for j in list(Ordering[i][1]):
               count+=1
               edges.append([i,j])
               self.inSet[j].append(i)
               self.outSet[i].append(j)
               ij_to_e[i,j] = count
           
           for j in list(Ordering[i][2]):
               count+=1
               edges.append([i,j])
               self.inSet[j].append(i)
               self.outSet[i].append(j)
               ij_to_e[i,j] = count
                   
       self.ij_to_e = ss.csc_matrix(ij_to_e, dtype=int)
       return edges
   
    
    def ConstraintLHS(self):
        A = np.empty(self.nvars, dtype=cplex.SparsePair)
        
        D = [[(self.tt[e,kk+1] - self.tt[e,kk])/(self.Theta[kk+1]-self.Theta[kk])  for kk in range(self.K)]for e in range(self.m)]

        #Loop through the columns of the constraint matrix
        for i in range(self.nvars):
            
            #first deal with the edge variables
            if i < self.m:
                
                ii = self.edges[i][0] if self.edges[i][0] < self.end else self.edges[i][0]-1
                ii2 = self.edges[i][1] if self.edges[i][1] < self.start else self.edges[i][1]-1
                
                inds = [ii, ii2+self.n-1, self.neqcons+i]
                vals = [1,1,-self.M]
                A[i] = cplex.SparsePair(ind = inds, val = vals);
            
            #next deal with the travel time variables
            elif i < 2*self.m:
                ii = self.edges[i-self.m][0]
                jj = self.edges[i-self.m][1]
                
                inds = [self.neqcons+i-self.m]+[self.neqcons+self.m + self.indexSlotMap(ii,jj,kk) for kk in self.departureSlots[ii]]
                vals = [-1]+[1 for _ in range(len(inds)-1)]
                
                A[i] = cplex.SparsePair(ind = inds, val = vals)
                
            #next the chi departure slot variables
            elif i <2*self.m +self.kappa:
                #the ik coordinates of this chi variable are:
                base = 2*self.m
                chii = self.slots[i-base][0]
                chik = self.slots[i-base][1]
                
                ind1 = [(chii if chii < self.end else chii-1) + 2*(self.n-1)]
                val1 = [1]
                
                ind2 = [self.neqcons + self.m + self.indexSlotMap(chii, jj, chik) for jj in self.outSet[chii]]
                val2 = [-self.M for _ in ind2]
                
                if chii!=self.end:
                    ind3 = [(chii if chii < self.end else chii -1)+self.neqcons+self.m +self.K2, (chii if chii < self.end else chii - 1)+self.neqcons+self.m +self.K2+self.n-1]
                    val3 = [-self.Theta[chik+1], -self.Theta[chik]]
                else:
                    ind3 = []
                    val3 = []

                vals = val1+val2+val3
                inds = ind1+ind2+ind3
                
                A[i] = cplex.SparsePair(ind = inds, val = vals)
            
            #now the arrival time dummy variables
            elif i <2*self.m + self.kappa + self.n:
                base = 2*self.m + self.kappa
                ii = i-base
                
                ind1 = [self.neqcons+ self.indexMap(jj, ii) for jj in self.inSet[ii]]
                val1 = [1 for _ in ind1]
                ind2 = [self.neqcons+self.indexMap(ii,jj) for jj in self.outSet[ii]]
                val2 = [-1 if ii else 0 for _ in ind2]
                                
                ind3 = [self.neqcons+self.m+ self.indexSlotMap(ii,jj,kk) for kk in self.departureSlots[ii] for jj in self.outSet[ii]]
                edges = [self.indexMap(ii,jj)  for jj in self.outSet[ii]]
                val3 = [-D[ee][ kk] if ii else 0 for kk in self.departureSlots[ii] for ee in edges]
                
                if ii != self.end:
                
                    ind4 = [(ii if ii < self.end else ii-1)+self.neqcons+self.m+self.K2  , (ii if ii < self.end else ii-1) +self.neqcons+self.m+self.K2+self.n-1]
                    val4 = [1 for _ in ind4]
                else:
                    ind4 = []
                    val4 = []
                    
                    
                if ii!= self.start:               
                    ind5 = [(ii if ii < self.start else ii-1) +self.neqcons+self.m + self.K2 + 2*(self.n-1)]
                    val5 = [1]
                else:
                    ind5 = []
                    val5 = []

                
                A[i] = cplex.SparsePair(ind = ind1+ind2+ind3+ind4+ind5, val = val1+val2+val3+val4+val5)
                
                #regret variable
            else:
                base = 2*self.m + self.kappa + self.n
                inds = [ii+self.neqcons + self.K2 +self.m + 2*(self.n-1) for ii in range(self.n -1)]
                vals = [-1 for _ in inds]
                
                A[i] = cplex.SparsePair(ind = inds, val = vals)
        return A;
    
    def ConstraintRHS(self):
        #the rhs for all equality bounds is 1
        b = np.ones(self.neqcons + self.nineqcons)
        
        for i in range(self.nineqcons):
            if i < self.m:
                #First the 'big M' constraint which relates T_i to T_j           
                b[self.neqcons +i] = (-self.M + self.service_time)
            elif i<self.K2+self.m:
                #Next the 'big M' constraint which determine travel time, with respect to time of day. There are K*m of these constraints, one for each edge per time window. We order these constraints such that constraint e*K + k refers to edge: 'e' and time windows 'k'.
                ee = self.indexMap(self.combos[i-self.m][0], self.combos[i-self.m][1])
                kk = self.combos[i-self.m][2]
                
                dddth = (self.tt[ee, kk+1]-self.tt[ee,kk])/(self.Theta[kk+1]-self.Theta[kk])
                tmp = self.tt[ee,kk] + dddth * (self.service_time - self.Theta[kk]) - self.M
                
                b[self.neqcons +i] = tmp
            
            elif i <self.K2+self.m + 2*self.n-2:
                #rhs for constraints which determine the chi variable, that is during which time slot the node i is departed from.
                b[self.neqcons+i] = -self.service_time
            elif i <self.K2+self.m + 3*(self.n)-2:
                #Finally we determine lateness
                b[self.neqcons+i] = self.DW[i-(self.K2+ self.m + 2*(self.n) +1), 1]
        
        

        return b
    
    def formulate(self):
        problem = cplex.Cplex();
        self.timestart = problem.get_time()
        problem.objective.set_sense(problem.objective.sense.minimize)
        
        names = ["x_"+str(i[0])+","+str(i[1]) for i in self.edges]+ ["t_"+str(i[0])+","+str(i[1]) for i in self.edges] + ["y_"+str(i[0])+","+str(i[1]) for i in self.slots] + ["a"+str(i) for i in range(self.n)]  +["r"]
        
        
        my_ubs = [1 for _ in range(self.m)] +[self.M for _ in range(self.m)]+[1 for _ in range(self.kappa)] +[self.M for i in range(self.n)] +[self.M]
        
        my_lbs = [0 for _ in range(2*self.m+self.kappa)]+[self.DW[j,0] for j in range(self.n)]+[-self.M]
        
        my_types = [problem.variables.type.binary for _ in range(self.m)]+[problem.variables.type.continuous for _ in range(self.m)]+[problem.variables.type.binary for _ in range(self.kappa)]+[problem.variables.type.continuous for _ in range(self.n)] +[problem.variables.type.continuous ]
        
        #self.RHS, con_type = self.ConstraintRHS()
        #self.LHS = self.ConstraintLHS()
        con_type = "E"*self.neqcons + "G"*(self.m+self.K2) + "L"*(self.n-1) + "G"*(self.n-1) + "L" *(self.n-1)
        #print(len(my_types), len(my_lbs), len(my_ubs), len(self.names), len(con_type))
        #print(len(self.obj), len(self.names), len(my_ubs), len(my_lbs), len(my_types), len(self.LHS))


        my_con_names = ["c"+str(i) for i in range(self.neqcons + self.nineqcons)]
        problem.linear_constraints.add( rhs = self.ConstraintRHS(), senses = con_type, names = my_con_names)
        
        
        
        #All of the lower bounds take the default value of 0
                
        
        #problem.write('debugging.lp')
        
        
        #print(self.obj)
        problem.variables.add(obj = self.obj, names = names, ub = my_ubs, lb = my_lbs, types = my_types, columns =  self.ConstraintLHS())
        #, columns =  self.LHS
        
        
        
        return problem
        
     
    def solve(self):
        p = self.formulate();
        
        p.solve();
        self.timeend = p.get_time()
        
        self.success = (p.solution.status[p.solution.get_status()]=='MIP_optimal')
        self.time_taken = self.timeend - self.timestart
        
        
        if self.success:
            sol = p.solution.get_values()
    
            self.edge_vals = sol[:self.m]
            self.travel_time_vals = sol[self.m:2*self.m]
            self.time_slot_vals = sol[2*self.m:2*self.m+self.kappa]
            self.arrival_time_vals = sol[2*self.m+self.kappa: 2*self.m+self.kappa+self.n]
            self.regret = sol[-1]
        
            return self.arrival_time_vals[self.end]
    
    def summary(self):
        
        if self.success:
            
            self.travelled_edges = [self.edges[i] for i in range(self.m) if self.edge_vals[i]]
            #self.applied_travel_times = [sol[self.m + i] for i in range(self.m) if sol[i]]
            
            self.route_info = [[self.edges[i], self.travel_time_vals[i]] for i in range(self.m) if self.edge_vals[i]]
            
            tour_route=[self.start];
            while len(tour_route)<self.n+1:
                node = tour_route[-1] if tour_route[-1] < self.end else tour_route[-1]-1
                tour_route.append(self.travelled_edges[node][1])
            print(tour_route)
            
            print(self.regret)
            print(self.arrival_time_vals)
            print(self.DW)
            print(self.time_taken)
            
        else:
            print('No solution exists')









#%%
            
toy_nnodes = 4;
ntw = 5;

start_time = 120;
end_node = 0
start_node = 2
alpha = 5
beta = 100
gamma = -950
service_time = 5
params = [toy_nnodes, service_time, start_node, end_node, alpha, hour]
tuning_params = [hour, 0.1]


hour = 60;

toy_customer_bounds = np.random.uniform(low=start_time,high=start_time + hour, size=toy_nnodes-1)

toy_DW = np.empty([toy_nnodes, 2])
toy_DW[0] = np.array([0, 8.5*hour])
toy_DW[1:,0] = toy_customer_bounds;
toy_DW[1:, 1] = toy_customer_bounds+hour;

toy_tt = np.array([[[0 if i==j else np.random.uniform(low = 5, high = 20) for k in range(ntw+1)] for i in range(toy_nnodes) ]for j in range(toy_nnodes)] )

#TW = np.sort(np.random.uniform(0, 8.5*hour, size=(ntw-1)))
toy_TW = np.linspace(-5, 10*hour, ntw+1)
#TW = []

tol_delay = 5
intol_delay = 10
alpha = 5
beta = 100

toy_pen_params = [5, hour]



#%%
tic = time.time()
toy = RTSPSubproblem(toy_DW, toy_tt, toy_TW, params, start_time)
#tmp= toy.formulate()
toy.solve()
#tmp.write('breakdown.lp')
toc = time.time()
print(300*(toc-tic))

#print('\n\n')
#print(toy.DW)
#print(toy.Theta)
#print('\n\n')

#print(toy.edges)  

#print(toy.ConstraintRHS())
#print(toy.ConstraintLHS())
#tmp = toy.formulate();
#tmp.write("current_test.lp")

#toy#%%

#toy.solve()

#%%
ans = toy.summary()
