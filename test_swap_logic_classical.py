def move_positions(a, current_data_pos, data_targets):
    n  = len(current_data_pos)

    position_to_index = {}
    for i in range(n):
        position_to_index[current_data_pos[i]] = i     
    for i in range(n):
        src = current_data_pos[i]
        des = data_targets[i]
        if src == des:
            continue
        
        try:
            j = position_to_index[des]
        except:
            j = None

        a[src], a[des] = a[des], a[src]

        current_data_pos[i] = des
        position_to_index[des] = i

        if j is not None:
            current_data_pos[j] = src
            position_to_index[src] = j
        else:
            position_to_index.pop(src, None)
    return a
  
print(move_positions([0,1,2,3,4,5,6,7,8,9],[1,3,5],[3,5,9]))