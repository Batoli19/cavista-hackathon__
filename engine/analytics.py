"""
Deprecated for clinical demo scope.
This module is retained for compatibility and is not used by the clinical MVP.
"""

from typing import List, Dict, Any
from datetime import date, timedelta, datetime

def calculate_critical_path(tasks: List[Dict[str, Any]]) -> List[str]:
    """
    Identifies tasks on the critical path.
    A simple implementation: finds the path with the longest duration sequence.
    Returns list of task IDs.
    """
    if not tasks:
        return []

    # 1. Build graph and calculate earliest start/finish
    # This is a simplified version assuming tasks are somewhat ordered or we just do a forward pass
    # For a hackathon, we can use the end dates computed by the scheduler if available, 
    # but let's do a standalone recursive search for the longest path to be robust.

    # Map id -> task
    task_map = {t["id"]: t for t in tasks}
    
    # Memoization for longest path to end from a given node
    memo = {}

    def get_path_duration(tid):
        if tid in memo:
            return memo[tid]
        
        t = task_map.get(tid)
        if not t:
            return 0
        
        duration = int(t.get("duration_days", 1)) + int(t.get("delay_days", 0))
        
        # Find max duration of dependencies
        # This is actually reverse: we want longest path leading TO this task? 
        # Or from this task?
        # Standard critical path: Longest path from Start to End.
        
        # Let's look at it as: End Date of Task = Max(End Date of Dependencies) + Duration
        # We can reuse the logic from engine.compute_schedule conceptually.
        pass

    # Re-using the schedule computation is easier and more accurate if we already have it.
    # Let's assume we can compute the schedule here or pass it in.
    # But let's write a standalone robust one.
    
    # 1. Compute Earliest Start (ES) and Earliest Finish (EF)
    es = {}
    ef = {}
    
    # Topological sort isn't strictly guaranteed, so we might need to iterate.
    # But assuming DAG.
    
    sorted_ids = [] # TODO: implement topo sort if needed, but let's assume input is roughly sorted or we do multi-pass
    
    # Naive multi-pass to settle dates (handles arbitrary order)
    for _ in range(len(tasks)):
        for t in tasks:
            tid = t["id"]
            duration = int(t.get("duration_days", 1)) + int(t.get("delay_days", 0))
            
            my_es = 0
            for dep_id in t.get("depends_on", []):
                if dep_id in ef:
                    my_es = max(my_es, ef[dep_id])
            
            es[tid] = my_es
            ef[tid] = my_es + duration

    project_duration = max(ef.values()) if ef else 0
    
    # 2. Compute Latest Start (LS) and Latest Finish (LF)
    # LF for last tasks = project_duration
    ls = {}
    lf = {tid: project_duration for tid in task_map}

    # Reverse pass
    # We need to process reverse dependencies. 
    # dependent_map: who depends on me?
    dependent_map = {tid: [] for tid in task_map}
    for t in tasks:
        for dep_id in t.get("depends_on", []):
            if dep_id in dependent_map:
                dependent_map[dep_id].append(t["id"])

    # Basic reverse pass logic (needs true reverse topo order, but repeated passes work for small N)
    for _ in range(len(tasks)):
        for t in tasks: # iterate all, but effective updates propagate
            tid = t["id"]
            duration = int(t.get("duration_days", 1)) + int(t.get("delay_days", 0))
            
            # My LF is min(LS of tasks that depend on me)
            my_lf = project_duration
            deps_on_me = dependent_map.get(tid, [])
            if deps_on_me:
                my_lf = min(ls.get(dtid, project_duration) for dtid in deps_on_me)
            
            lf[tid] = my_lf
            ls[tid] = my_lf - duration
            
    # 3. Critical Path: ES == LS (Slack == 0)
    critical_path = []
    for tid in task_map:
        if abs(es.get(tid, -1) - ls.get(tid, -2)) < 0.01: # float tolerance just in case
            critical_path.append(tid)
            
    return critical_path

def diagnose_project(project: Dict[str, Any]) -> List[str]:
    """
    Analyzes the project and returns a list of text recommendations.
    """
    recommendations = []
    tasks = project.get("tasks", [])
    if not tasks:
        return ["Add some tasks to get started."]

    critical_path = calculate_critical_path(tasks)
    
    # 1. Deadline Check
    # This requires running the schedule logic, which we can approximate or replicate
    # Let's replicate the simple schedule logic from engine.py locally to be safe
    # or just analyze delays.
    
    total_delay = 0
    max_delay_task = None
    max_delay = 0
    
    for t in tasks:
        d = int(t.get("delay_days", 0))
        total_delay += d
        if d > max_delay:
            max_delay = d
            max_delay_task = t

    if total_delay > 0:
        recommendations.append(f"Project has accumulated {total_delay} days of total delay.")

    if max_delay_task:
        tid = max_delay_task["id"]
        if tid in critical_path:
            recommendations.append(f"CRITICAL: Task '{max_delay_task['name']}' is delayed by {max_delay} days and is blocking the project. IMMEDIATE ACTION: Add resources to this task.")
        else:
            recommendations.append(f"Task '{max_delay_task['name']}' is delayed by {max_delay} days but is not critical. Monitor it.")

    # 2. Priority check
    high_priority_count = sum(1 for t in tasks if t.get("priority") == "high")
    if high_priority_count > len(tasks) * 0.5:
         recommendations.append("Warning: More than 50% of tasks are marked 'High Priority'. Everything is critical = nothing is critical. Re-evaluate priorities.")

    # 3. Role Bottlenecks (Simple)
    # If we had a team list, we could check capacity. 
    # For now, just check if one role is overloaded?
    role_counts = {}
    for t in tasks:
        r = t.get("role", "general")
        role_counts[r] = role_counts.get(r, 0) + 1
    
    most_used_role = max(role_counts, key=role_counts.get)
    if role_counts[most_used_role] > len(tasks) * 0.7:
         recommendations.append(f"Bottleneck Warning: {role_counts[most_used_role]} tasks leverage '{most_used_role}'. Ensure you have enough {most_used_role}s.")

    if not recommendations:
        recommendations.append("Project looks healthy! Keep it up.")

    return recommendations
