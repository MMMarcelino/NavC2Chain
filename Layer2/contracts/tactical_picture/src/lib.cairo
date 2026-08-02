use starknet::ContractAddress;

#[derive(Drop, Copy, Serde, starknet::Store)]
pub struct Report {
    pub timestamp: u64,
    pub lat: u64,
    pub lon: u64,
    pub depth_alt: u64,
    pub status: felt252,
}

#[starknet::interface]
pub trait ITacticalPicture<T> {
    fn report_position(ref self: T, lat: u64, lon: u64, depth_alt: u64, status: felt252);
    fn report_contact(ref self: T, bearing_deg: u16, range_m: u32, classification: felt252);
    fn get_last_report(self: @T, uxv: ContractAddress) -> Report;
    fn total_reports(self: @T) -> u64;
    fn total_contacts(self: @T) -> u64;
}

#[starknet::contract]
pub mod TacticalPicture {
    use starknet::{ContractAddress, get_caller_address, get_block_timestamp};
    use starknet::storage::{
        Map, StoragePointerReadAccess, StoragePointerWriteAccess, StoragePathEntry,
    };
    use super::Report;

    #[storage]
    struct Storage {
        last_report: Map<ContractAddress, Report>,
        reports_total: u64,
        contacts_total: u64,
    }

    #[event]
    #[derive(Drop, starknet::Event)]
    pub enum Event {
        PositionReported: PositionReported,
        ContactReported: ContactReported,
    }

    #[derive(Drop, starknet::Event)]
    pub struct PositionReported {
        #[key]
        pub uxv: ContractAddress,
        pub timestamp: u64,
        pub lat: u64,
        pub lon: u64,
        pub depth_alt: u64,
        pub status: felt252,
    }

    #[derive(Drop, starknet::Event)]
    pub struct ContactReported {
        #[key]
        pub uxv: ContractAddress,
        pub timestamp: u64,
        pub bearing_deg: u16,
        pub range_m: u32,
        pub classification: felt252,
    }

    #[abi(embed_v0)]
    impl TacticalPictureImpl of super::ITacticalPicture<ContractState> {
        fn report_position(
            ref self: ContractState, lat: u64, lon: u64, depth_alt: u64, status: felt252,
        ) {
            let uxv = get_caller_address();
            let ts = get_block_timestamp();
            self.last_report.entry(uxv).write(Report { timestamp: ts, lat, lon, depth_alt, status });
            self.reports_total.write(self.reports_total.read() + 1);
            self.emit(PositionReported { uxv, timestamp: ts, lat, lon, depth_alt, status });
        }

        fn report_contact(
            ref self: ContractState, bearing_deg: u16, range_m: u32, classification: felt252,
        ) {
            let uxv = get_caller_address();
            let ts = get_block_timestamp();
            self.contacts_total.write(self.contacts_total.read() + 1);
            self.emit(ContactReported { uxv, timestamp: ts, bearing_deg, range_m, classification });
        }

        fn get_last_report(self: @ContractState, uxv: ContractAddress) -> Report {
            self.last_report.entry(uxv).read()
        }

        fn total_reports(self: @ContractState) -> u64 { self.reports_total.read() }
        fn total_contacts(self: @ContractState) -> u64 { self.contacts_total.read() }
    }
}
