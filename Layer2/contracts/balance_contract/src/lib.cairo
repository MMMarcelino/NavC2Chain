#[starknet::interface]
trait IBalance<T> {
    fn get(self: @T) -> felt252;
    fn increase(ref self: T, a: felt252);
}

#[starknet::contract]
mod Balance {
    use starknet::storage::{ StoragePointerReadAccess, StoragePointerWriteAccess };

    #[storage]
    struct Storage {
        value: felt252,
    }

    #[constructor]
    fn constructor(ref self: ContractState) {
        self.value.write(5);
    }

    #[abi(embed_v0)]
    impl Balance of super::IBalance<ContractState> {
        fn get(self: @ContractState) -> felt252 {
            self.value.read()
        }
        fn increase(ref self: ContractState, a: felt252) {
            self.value.write(self.value.read() + a);
        }
    }
}
