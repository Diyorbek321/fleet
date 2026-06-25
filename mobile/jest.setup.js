// Provide a working in-memory AsyncStorage in the test environment. The native
// module is unavailable under Jest, so we swap in the package's official mock.
jest.mock('@react-native-async-storage/async-storage', () =>
  require('@react-native-async-storage/async-storage/jest/async-storage-mock'),
);
