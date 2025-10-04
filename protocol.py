from qiskit import QuantumCircuit, transpile, ClassicalRegister
from qiskit_aer import AerSimulator
from qiskit_aer.noise import NoiseModel
from qiskit_ibm_runtime import QiskitRuntimeService
from dotenv import load_dotenv
import os
import random
import argparse
load_dotenv()

QBER_THRESHOLD = 0.1
# Turn qubit q into a decoy which is one of |+>, |->, |y+> or |y->
def make_decoy(qc: QuantumCircuit, q:int, basis: str, sign: str):
    qc.reset(q)
    if basis == 'X':
        qc.h(q)
        if sign == '-':
            qc.z(q)
    elif basis == 'Y':
        qc.h(q)
        qc.s(q)
        if sign == '-':
            qc.z(q)

def projective_measurement_in_basis(qc: QuantumCircuit, q:int, c:int, basis:str):
    if basis == 'X':
        qc.h(q)
    elif basis == 'Y':
        qc.sdg(q)
        qc.h(q)
    else:
        raise ValueError("Basis must be either X or Y")
    qc.measure(q,c)


def eve_does_random_unitary_op(qc: QuantumCircuit, target_qubits: list[int], probability: float, random_generator: random.Random):
    for qubit in target_qubits:
        if random_generator.random() <= probability:
            gate = random_generator.choice(["X","Y","Z"])
            if gate == 'X':
                qc.x(qubit)
            elif gate == 'Y':
                qc.y(qubit)
            else:
                qc.z(qubit)

def eve_intercept_resend(qc: QuantumCircuit, probability: float, random_generator: random.Random, eve_classical_register:ClassicalRegister):
    for qubit in range(qc.num_qubits):
        p = random_generator.random()
        if  p <= probability:
            gate = random_generator.choice(["X","Y","Z"])
            if gate == 'X':
                qc.h(qubit)
            elif gate == 'Y':
                qc.sdg(qubit)
                qc.h(qubit)
            qc.measure(qubit, eve_classical_register[qubit])
            qc.reset(qubit)
            if gate == 'X':
                qc.h(qubit)
                if eve_classical_register[qubit] == 1:
                    qc.z(qubit)
            elif gate == 'Y':
                qc.h(qubit)
                qc.s(qubit)
                if eve_classical_register[qubit] == 1:
                    qc.z(qubit)


def create_noise_model() -> NoiseModel | None:
    try:
        QiskitRuntimeService.save_account(token=os.getenv("IBM_API_KEY"), instance=os.getenv("INSTANCE_CRN"),overwrite=True)
        service = QiskitRuntimeService()
        least_busy_back_end = service.least_busy()
        noise_model = NoiseModel.from_backend(least_busy_back_end)
    except Exception as e:
        print(e)
        return None
    return noise_model

def decoys_data_positions(random_generator:random.Random, number_of_qubits:int, number_of_decoys:int)-> tuple[list[int],list[int]]:
    decoys_positions = sorted(random_generator.sample(range(number_of_qubits),k=number_of_decoys))
    data_positions = []
    for i in range(number_of_qubits):
        if i not in decoys_positions:
            data_positions.append(i)
    return decoys_positions,data_positions
#Uses swap gate to move data qubits around while maintaining their relative positions with one another
#This function leave spaces for decoys to be injected later
def rearrange_data_qubits_in_circuits(qc:QuantumCircuit, current_data_positions:list[int], target_data_positions:list[int]):
    if len(current_data_positions) != len(target_data_positions):
        raise ValueError("Unequal length")
    n = len(current_data_positions)
    position_to_index = {}
    for i in range(n):
        position_to_index[current_data_positions[i]] = i
    for i in range(n):
        source = current_data_positions[i]
        destination = target_data_positions[i]
        if source == destination:
            continue
        try:
            k = position_to_index[destination]
        except:
            k = None
        qc.swap(source,destination)
        current_data_positions[i] = destination
        position_to_index[destination] = i
        if k is None:
            position_to_index.pop(source,None)
        else:
            current_data_positions[k] = source
            position_to_index[source] = k

def ring_quantum_circuit(number_of_qubits: int, decoy_rate:float, number_of_participants:int, eve_attack_times: list[int],
                          random_generator: random.Random, eve_attack_mode: str = "off", eve_attack_probability :float = 0.3) -> tuple[QuantumCircuit,list[list[int]]]:
    
    qc = QuantumCircuit(number_of_qubits)
    number_of_decoys = max(1,int(number_of_qubits*decoy_rate))


    eve_classical_register = None
    if eve_attack_mode == "intercept_resend":
        eve_classical_register =  ClassicalRegister(number_of_qubits,"attacker")
        qc.add_register(eve_classical_register)

    #Using separate decoy register for each turn to track qber
    decoy_registers = []
    #There are 'number_of_participants' turns in total
    for i in range(number_of_participants):
        turn_i_decoy_register = ClassicalRegister(number_of_decoys,f"decoys regs {i}")
        qc.add_register(turn_i_decoy_register)
        decoy_registers.append(turn_i_decoy_register)
    
    data_register = ClassicalRegister(number_of_qubits - number_of_decoys,"Data")
    qc.add_register(data_register)
    #Each iteration represent a send and receive step between Pi and Pi+1
    current_data_positions = []
    
    for i in range(number_of_qubits - number_of_decoys):
        current_data_positions.append(i)

    expected_decoys_measurements = []
    for i in range(number_of_participants):
        sender = i
        receiver = (i+1) % number_of_participants
        qc.barrier(label=f"{sender} change data positions for turn{i}")
        decoys_positions,data_positions = decoys_data_positions(random_generator,number_of_qubits,number_of_decoys)
        # Rearrange data qubits but maintain relative positioning so decoys can be inserted
        rearrange_data_qubits_in_circuits(qc,current_data_positions,data_positions)
        qc.barrier(label=f"{sender} make decoys for turn {i}")

        turn_expected_measurement = []
        turn_bases = []
        for qubit in decoys_positions:
            basis = random_generator.choice(["X","Y"])
            sign = random_generator.choice(["+","-"])
            turn_bases.append(basis)
            if sign == "+":
                turn_expected_measurement.append(0)
            else:
                turn_expected_measurement.append(1)
            make_decoy(qc,qubit,basis,sign)
        if eve_attack_mode != "off" and i in eve_attack_times:
            qc.barrier(label=f"Eve attacks turn {i}")
            if eve_attack_mode == "random_stuff_go":
                eve_does_random_unitary_op(qc,list(range(number_of_qubits)),eve_attack_probability,random_generator)
            elif eve_attack_mode == "intercept_resend":
                eve_intercept_resend(qc,eve_attack_probability,random_generator,eve_classical_register)
        qc.barrier(label=f"{receiver} measure decoys for turn {i}")
        for j in range(len(decoys_positions)):
            projective_measurement_in_basis(qc,decoys_positions[j],decoy_registers[i][j],turn_bases[j])
            qc.reset(decoys_positions[j])
        expected_decoys_measurements.append(turn_expected_measurement)

        # Now encode data with either I or Y
        qc.barrier(label=f"{sender} encode Y ")
        senders_key = []

        for position  in data_positions:
            senders_key.append(random_generator.randint(0,1))
            if senders_key[-1] == 1:
                qc.x(position)
                qc.z(position)
        print(f"Sender {sender} key is: ", senders_key)
    qc.barrier(label="Final measurement to reveal key")
    for i in range(len(current_data_positions)):
        qc.measure(current_data_positions[i], data_register[i])
    return qc,expected_decoys_measurements

def caculate_qber(actual_measurement_results:list[int], expected_measurement: list[int]) -> float:
    if len(actual_measurement_results) != len(expected_measurement) or len(expected_measurement) < 1:
        raise ValueError("Inconsistency in the number of measurements")
    number_of_wrong_qubit = 0
    for i in range(len(expected_measurement)):
        if expected_measurement[i] != actual_measurement_results[i]:
            number_of_wrong_qubit +=1
    return number_of_wrong_qubit / len(expected_measurement)
def run_protocol(seed:int, number_of_participants:int, eve_attack_mode:str, eve_attack_probability:float, number_of_qubits:int, decoy_rate:float):
    # Use for reproducibility
    random_generator = random.Random(seed)
    eve_attack_times = []
    for i in range(number_of_participants):
        if random_generator.randint(0,1) == 1:
            eve_attack_times.append(i)
    qc, expected_decoys_measurements = ring_quantum_circuit(number_of_qubits,decoy_rate,number_of_participants,
                                                        eve_attack_times,random_generator,eve_attack_mode,eve_attack_probability)
    qc.draw(output="mpl", filename="ring_circuit.png")
    noise_model = create_noise_model()
    if noise_model != None:
        back_end = AerSimulator(noise_model)
    else:
        back_end = AerSimulator()
    transpiled_circuit = transpile(qc,back_end)
    result = back_end.run(transpiled_circuit, shot=1,memory=True,seed_simulator=seed).result()
    memory = result.get_memory(transpiled_circuit)[0]
    # Should contain 3 type of register, belonging to eve, decoys and data
    # Eve's register is the first one, follows by 'number_of_participants' number of decoy register (one for each turn) and finally data's register
    registers = memory.split(" ")[::-1]
    print(registers)
    index = 0
    if eve_attack_mode == "intercept_resend":
        index += 1
    passed = True
    for i in range(number_of_participants):
        decoy_measurement_result = []
        temp = registers[index][::-1]
        for j in range(len(temp)):
            decoy_measurement_result.append(int(temp[j]))
        expected_measurement_result = expected_decoys_measurements[i]
        qber = caculate_qber(decoy_measurement_result,expected_measurement_result)
        print(qber)
        if qber > QBER_THRESHOLD:
            print(f"TOO MUCH ERROR, PROTOCOL ABANDONED. QBER = ",qber)
            passed = False
            break
            
        index += 1
    if passed:
        print(f"PROTOCOL SUCCEEDED. AGREED KEY IS: {registers[index][::-1]}")
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--eve_mode", type=str, default="off",
                        choices=["off", "random_stuff_go", "intercept_resend"],
                        help="Eve's attack mode.")
    parser.add_argument("--eve_p", type=float, default=0.3,
                        help="Eve's per-qubit attack probability in [0,1].")
    parser.add_argument("--n_parties", type=int, default=3,
                        help="Number of participants in the ring.")
    parser.add_argument("--seed", type=int, default=77777,
                        help="Random seed for reproducibility.")
    parser.add_argument("--n_qubits", type=int, default=16,
                        help="Total qubits = data + decoys.")
    parser.add_argument("--decoy_rate", type=float, default=0.5,
                        help="Ratio between decoys and total number of qubits")
    args = parser.parse_args()

    run_protocol(
        seed=args.seed,
        number_of_participants=args.n_parties,
        eve_attack_mode=args.eve_mode,
        eve_attack_probability=args.eve_p,
        number_of_qubits=args.n_qubits,
        decoy_rate=args.decoy_rate
    )