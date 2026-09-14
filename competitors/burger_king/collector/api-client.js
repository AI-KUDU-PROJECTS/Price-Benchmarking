'use strict';

/**
 * collector/api-client.js
 * ---------------------------------------------------------------------
 * Typed wrappers around Burger King Saudi's real GraphQL endpoints (see
 * research/api-map/api-map.md for the full reference, verification notes,
 * and the live-confirmed fact that none of these need cookies/auth/a
 * browser session - every query below was replayed standalone with a
 * plain Node https request during development and returned real data).
 *
 * Every wrapper follows the same shape as competitors/kfc's api-client.js:
 * async fn(...args, logger) -> { ok, status, data, raw, error, schema }.
 * Never throws on a bad response - callers (channel-collector.js) decide
 * what a FAILED schema check means for run status.
 * ---------------------------------------------------------------------
 */

const http = require('./http-client');
const CONFIG = require('./config');

// --- Real queries captured + standalone-replay-verified during development ---
const GET_RESTAURANTS_QUERY = "query GetRestaurants($input: RestaurantsInput) {\n  restaurants(input: $input) {\n    pageInfo {\n      hasNextPage\n      endCursor\n      __typename\n    }\n    totalCount\n    nodes {\n      ...RestaurantNodeFragment\n      __typename\n    }\n    __typename\n  }\n}\n\nfragment RestaurantNodeFragment on RestaurantNode {\n  _id\n  storeId\n  isAvailable\n  posVendor\n  chaseMerchantId\n  curbsideHours {\n    ...OperatingHoursFragment\n    __typename\n  }\n  currentLocalTime\n  cybersourceTransactingId\n  deliveryHours {\n    ...OperatingHoursFragment\n    __typename\n  }\n  deliveryOrderAmountLimit {\n    ...DeliveryOrderAmountLimitFragment\n    __typename\n  }\n  diningRoomHours {\n    ...OperatingHoursFragment\n    __typename\n  }\n  distanceInMiles\n  drinkStationType\n  driveThruHours {\n    ...OperatingHoursFragment\n    __typename\n  }\n  driveThruLaneType\n  email\n  environment\n  franchiseGroupId\n  franchiseGroupName\n  frontCounterClosed\n  hasBirthdayReservation\n  hasBreakfast\n  hasBurgersForBreakfast\n  hasCatering\n  hasCurbside\n  hideClickAndCollectOrdering\n  hasDelivery\n  hasDineIn\n  hasDriveThru\n  hasTableService\n  hasMobileOrdering\n  hasLateNightMenu\n  hasParking\n  hasPlayground\n  hasTakeOut\n  hasWifi\n  hasLoyalty\n  id\n  isDarkKitchen\n  isFavorite\n  isHalal\n  isRecent\n  latitude\n  longitude\n  mobileOrderingStatus\n  name\n  number\n  parkingType\n  paymentMethods {\n    ...PaymentMethodsFragment\n    __typename\n  }\n  phoneNumber\n  physicalAddress {\n    address1\n    address2\n    city\n    country\n    postalCode\n    stateProvince\n    stateProvinceShort\n    __typename\n  }\n  playgroundType\n  pos {\n    vendor\n    __typename\n  }\n  paymentProcessor\n  posRestaurantId\n  restaurantImage {\n    asset {\n      _id\n      metadata {\n        lqip\n        __typename\n      }\n      __typename\n    }\n    crop {\n      top\n      bottom\n      left\n      right\n      __typename\n    }\n    hotspot {\n      height\n      width\n      x\n      y\n      __typename\n    }\n    __typename\n  }\n  restaurantPosData {\n    _id\n    __typename\n  }\n  showStoreLocatorOffersButton\n  status\n  vatNumber\n  customerFacingAddress {\n    locale\n    __typename\n  }\n  waitTime {\n    queueLength\n    firingTimestamp\n    __typename\n  }\n  integration {\n    isPartnerRestaurant\n    partnerGroup {\n      name\n      posIntegration {\n        _ref\n        _type\n        __typename\n      }\n      __typename\n    }\n    __typename\n  }\n  __typename\n}\n\nfragment OperatingHoursFragment on OperatingHours {\n  friClose\n  friOpen\n  friAdditionalTimeSlot {\n    ...AdditionalTimeSlotFragment\n    __typename\n  }\n  monClose\n  monOpen\n  monAdditionalTimeSlot {\n    ...AdditionalTimeSlotFragment\n    __typename\n  }\n  satClose\n  satOpen\n  satAdditionalTimeSlot {\n    ...AdditionalTimeSlotFragment\n    __typename\n  }\n  sunClose\n  sunOpen\n  sunAdditionalTimeSlot {\n    ...AdditionalTimeSlotFragment\n    __typename\n  }\n  thrClose\n  thrOpen\n  thrAdditionalTimeSlot {\n    ...AdditionalTimeSlotFragment\n    __typename\n  }\n  tueClose\n  tueOpen\n  tueAdditionalTimeSlot {\n    ...AdditionalTimeSlotFragment\n    __typename\n  }\n  wedClose\n  wedOpen\n  wedAdditionalTimeSlot {\n    ...AdditionalTimeSlotFragment\n    __typename\n  }\n  __typename\n}\n\nfragment AdditionalTimeSlotFragment on AdditionalTimeSlot {\n  open\n  close\n  _type\n  __typename\n}\n\nfragment DeliveryOrderAmountLimitFragment on DeliveryOrderAmountLimit {\n  deliveryOrderAmountLimit\n  deliveryOrderAmountLimitEnabled\n  deliveryOrderRepeatedFailureLimitation\n  firstDeliveryOrder\n  firstDeliveryOrderEnabled\n  __typename\n}\n\nfragment PaymentMethodsFragment on PaymentMethods {\n  name\n  paymentMethodBrand\n  state\n  isOnlinePayment\n  __typename\n}";
const GET_RESTAURANT_QUERY = "query GetRestaurant($storeId: String, $storeNumber: String) {\n  restaurant(storeId: $storeId, storeNumber: $storeNumber) {\n    available\n    curbsideHours {\n      ...OperatingHoursFragment\n      __typename\n    }\n    deliveryHours {\n      ...OperatingHoursFragment\n      __typename\n    }\n    diningRoomHours {\n      ...OperatingHoursFragment\n      __typename\n    }\n    driveThruHours {\n      ...OperatingHoursFragment\n      __typename\n    }\n    currentLocalTime\n    __typename\n  }\n}\n\nfragment OperatingHoursFragment on OperatingHours {\n  friClose\n  friOpen\n  friAdditionalTimeSlot {\n    ...AdditionalTimeSlotFragment\n    __typename\n  }\n  monClose\n  monOpen\n  monAdditionalTimeSlot {\n    ...AdditionalTimeSlotFragment\n    __typename\n  }\n  satClose\n  satOpen\n  satAdditionalTimeSlot {\n    ...AdditionalTimeSlotFragment\n    __typename\n  }\n  sunClose\n  sunOpen\n  sunAdditionalTimeSlot {\n    ...AdditionalTimeSlotFragment\n    __typename\n  }\n  thrClose\n  thrOpen\n  thrAdditionalTimeSlot {\n    ...AdditionalTimeSlotFragment\n    __typename\n  }\n  tueClose\n  tueOpen\n  tueAdditionalTimeSlot {\n    ...AdditionalTimeSlotFragment\n    __typename\n  }\n  wedClose\n  wedOpen\n  wedAdditionalTimeSlot {\n    ...AdditionalTimeSlotFragment\n    __typename\n  }\n  __typename\n}\n\nfragment AdditionalTimeSlotFragment on AdditionalTimeSlot {\n  open\n  close\n  _type\n  __typename\n}";
const DELIVERY_RESTAURANT_QUERY = "query DeliveryRestaurant($dropoff: DeliveryWaypointInput!, $searchRadius: Float!, $platform: Platform!) {\n  deliveryRestaurant(\n    dropoff: $dropoff\n    searchRadius: $searchRadius\n    platform: $platform\n  ) {\n    storeStatus\n    quote\n    nextEarliestOpen\n    deliverySurchargeFeeCents\n    quoteId\n    unavailabilityReason\n    preOrderTimeSlots {\n      start\n      end\n      __typename\n    }\n    restaurant {\n      ...DeliveryRestaurantNodeFragment\n      __typename\n    }\n    __typename\n  }\n}\n\nfragment DeliveryRestaurantNodeFragment on DeliveryRestaurantNode {\n  id\n  _id\n  storeId\n  name\n  number\n  status\n  isAvailable\n  latitude\n  longitude\n  paymentProcessor\n  cybersourceTransactingId\n  deliveryOrderAmountLimit {\n    deliveryOrderAmountLimit\n    deliveryOrderAmountLimitEnabled\n    deliveryOrderRepeatedFailureLimitation\n    firstDeliveryOrder\n    firstDeliveryOrderEnabled\n    __typename\n  }\n  physicalAddress {\n    address1\n    address2\n    city\n    country\n    postalCode\n    stateProvince\n    stateProvinceShort\n    __typename\n  }\n  customerFacingAddress {\n    locale\n    __typename\n  }\n  hasCurbside\n  hasDelivery\n  hasDriveThru\n  hasDineIn\n  hasMobileOrdering\n  hasTakeOut\n  hasTableService\n  hideClickAndCollectOrdering\n  mobileOrderingStatus\n  curbsideHours {\n    ...DeliveryOperatingHoursFragment\n    __typename\n  }\n  deliveryHours {\n    ...DeliveryOperatingHoursFragment\n    __typename\n  }\n  diningRoomHours {\n    ...DeliveryOperatingHoursFragment\n    __typename\n  }\n  driveThruHours {\n    ...DeliveryOperatingHoursFragment\n    __typename\n  }\n  pos {\n    vendor\n    __typename\n  }\n  integration {\n    isPartnerRestaurant\n    partnerGroup {\n      name\n      posIntegration {\n        _ref\n        _type\n        __typename\n      }\n      __typename\n    }\n    __typename\n  }\n  phoneNumber\n  franchiseGroupId\n  franchiseGroupName\n  vatNumber\n  posRestaurantId\n  restaurantPosData {\n    _id\n    __typename\n  }\n  __typename\n}\n\nfragment DeliveryOperatingHoursFragment on OperatingHours {\n  monOpen\n  monClose\n  monAdditionalTimeSlot {\n    _type\n    open\n    close\n    __typename\n  }\n  tueOpen\n  tueClose\n  tueAdditionalTimeSlot {\n    _type\n    open\n    close\n    __typename\n  }\n  wedOpen\n  wedClose\n  wedAdditionalTimeSlot {\n    _type\n    open\n    close\n    __typename\n  }\n  thrOpen\n  thrClose\n  thrAdditionalTimeSlot {\n    _type\n    open\n    close\n    __typename\n  }\n  friOpen\n  friClose\n  friAdditionalTimeSlot {\n    _type\n    open\n    close\n    __typename\n  }\n  satOpen\n  satClose\n  satAdditionalTimeSlot {\n    _type\n    open\n    close\n    __typename\n  }\n  sunOpen\n  sunClose\n  sunAdditionalTimeSlot {\n    _type\n    open\n    close\n    __typename\n  }\n  __typename\n}";
const GET_MENU_SECTIONS_QUERY = "query GetMenuSections($id:ID!){Menu(id:$id){_id _type name{locale:en _locFb:ar __typename}image{...ImageFragment __typename}options{...ProductListSectionFragment ...PickerFragment __typename}headerText{locale:en _locFb:ar __typename}pickerBackgroundImage{asset{_id __typename}__typename}__typename}}fragment ImageFragment on Image{hotspot{x y height width __typename}crop{top bottom left right __typename}asset{metadata{lqip __typename}_id url __typename}__typename}fragment ProductListSectionFragment on Section{_id _type daypart name{locale:en _locFb:ar __typename}image{...ImageFragment __typename}uiPattern showInStaticMenu isBurgersForBreakfastSection headerText{locale:en _locFb:ar __typename}imageDescription{locale:en _locFb:ar __typename}carouselImage{...ImageFragment __typename}hiddenFromMainMenu options{...on Section{_id _type name{locale:en _locFb:ar __typename}image{...ImageFragment __typename}headerText{locale:en _locFb:ar __typename}imageDescription{locale:en _locFb:ar __typename}carouselImage{...ImageFragment __typename}hiddenFromMainMenu options{...on Item{_id _type name{locale:en _locFb:ar __typename}image{...ImageFragment __typename}imagesByChannels{...ImagesByChannelsFragment __typename}showInStaticMenu hideCalories channelExclusions{delivery pickup web mobile __typename}options{...on ItemOption{options{modifierMultiplier{_id vendorConfigs{...VendorConfigsFragment __typename}__typename}pluConfigs{...PluConfigsFragment __typename}__typename}__typename}__typename}itemSize itemUnit __typename}...on Picker{_id _type name{locale:en _locFb:ar __typename}description{localeRaw:enRaw _locFbRaw:arRaw __typename}image{...ImageFragment __typename}imagesByChannels{...ImagesByChannelsFragment __typename}uiPattern showInStaticMenu channelExclusions{delivery pickup web mobile __typename}depositInfoText{locale:en _locFb:ar __typename}pickerAspects{_id name{locale:en _locFb:ar __typename}pickerAspectOptions{identifier name{locale:en _locFb:ar __typename}__typename}__typename}options{type:_type _key default pickerItemMappings{pickerAspectValueIdentifier __typename}option{...on Item{_id _type name{locale:en _locFb:ar __typename}__typename}...on Combo{_id _type name{locale:en _locFb:ar __typename}__typename}__typename}__typename}__typename}...on Combo{_id _type name{locale:en _locFb:ar __typename}image{...ImageFragment __typename}imagesByChannels{...ImagesByChannelsFragment __typename}uiPattern showInStaticMenu channelExclusions{delivery pickup __typename}depositInfoText{locale:en _locFb:ar __typename}__typename}__typename}channelExclusions{delivery pickup web mobile __typename}uiPattern showInStaticMenu daypart isBurgersForBreakfastSection __typename}...on Combo{_id _type name{locale:en _locFb:ar __typename}image{...ImageFragment __typename}imagesByChannels{...ImagesByChannelsFragment __typename}uiPattern showInStaticMenu channelExclusions{delivery pickup web mobile __typename}depositInfoText{locale:en _locFb:ar __typename}__typename}...on Picker{_id _type name{locale:en _locFb:ar __typename}description{localeRaw:enRaw _locFbRaw:arRaw __typename}image{...ImageFragment __typename}imagesByChannels{...ImagesByChannelsFragment __typename}uiPattern showInStaticMenu channelExclusions{delivery pickup web mobile __typename}depositInfoText{locale:en _locFb:ar __typename}pickerAspects{_id name{locale:en _locFb:ar __typename}pickerAspectOptions{identifier name{locale:en _locFb:ar __typename}__typename}__typename}options{type:_type _key default pickerItemMappings{pickerAspectValueIdentifier __typename}option{...on Item{_id _type name{locale:en _locFb:ar __typename}__typename}...on Combo{_id _type name{locale:en _locFb:ar __typename}__typename}__typename}__typename}__typename}...on Item{_id _type name{locale:en _locFb:ar __typename}image{...ImageFragment __typename}imagesByChannels{...ImagesByChannelsFragment __typename}showInStaticMenu hideCalories channelExclusions{delivery pickup web mobile __typename}options{...on ItemOption{options{modifierMultiplier{_id vendorConfigs{...VendorConfigsFragment __typename}__typename}pluConfigs{...PluConfigsFragment __typename}__typename}__typename}__typename}itemSize itemUnit __typename}__typename}channelExclusions{delivery pickup web mobile __typename}__typename}fragment ImagesByChannelsFragment on ImagesByChannels{imageRestaurant{asset{_id metadata{lqip __typename}__typename}__typename}imageDelivery{asset{_id metadata{lqip __typename}__typename}__typename}__typename}fragment VendorConfigsFragment on VendorConfigs{ncr{...VendorConfigFragment __typename}ncrDelivery{...VendorConfigFragment __typename}partner{...VendorConfigFragment __typename}partnerDelivery{...VendorConfigFragment __typename}productNumber{...VendorConfigFragment __typename}productNumberDelivery{...VendorConfigFragment __typename}sicom{...VendorConfigFragment __typename}sicomDelivery{...VendorConfigFragment __typename}qdi{...VendorConfigFragment __typename}qdiDelivery{...VendorConfigFragment __typename}rpos{...VendorConfigFragment __typename}rposDelivery{...VendorConfigFragment __typename}simplyDelivery{...VendorConfigFragment __typename}simplyDeliveryDelivery{...VendorConfigFragment __typename}toshibaLoyalty{...VendorConfigFragment __typename}__typename}fragment VendorConfigFragment on VendorConfig{pluType parentSanityId pullUpLevels constantPlu discountPlu quantityBasedPlu{quantity plu qualifier __typename}multiConstantPlus{quantity plu qualifier __typename}parentChildPlu{plu childPlu __typename}sizeBasedPlu{comboPlu comboSize __typename}__typename}fragment PluConfigsFragment on PluConfigs{_key _type partner{...PluConfigFragment __typename}__typename}fragment PluConfigFragment on PluConfig{_key _type posIntegration{_id _type name __typename}serviceMode vendorConfig{...VendorConfigFragment __typename}__typename}fragment PickerFragment on Picker{_id _type name{locale:en _locFb:ar __typename}pickerDefaults{_key pickerAspect{_id name{locale:en _locFb:ar __typename}__typename}pickerAspectValueIdentifier __typename}pickerAspects{_id _type name{locale:en _locFb:ar __typename}uiPattern pickerAspectOptions{identifier name{locale:en _locFb:ar __typename}description{locale:en _locFb:ar __typename}image{...MenuImageFragment __typename}imageDescription{locale:en _locFb:ar __typename}hideNameInItemPreview showInStaticMenu __typename}__typename}pickerAspectItemOptionMappings{pickerAspect{_id name{locale:en _locFb:ar __typename}__typename}options{value __typename}__typename}options{type:_type _key pickerItemMappings{pickerAspectValueIdentifier pickerAspect{_id __typename}__typename}option{...on Combo{_key _id promotion{bonusPoints __typename}...ComboFragment __typename}...on Item{_key promotion{bonusPoints __typename}...ItemFragment __typename}__typename}default __typename}image{...MenuImageFragment __typename}imageDescription{locale:en _locFb:ar __typename}description{localeRaw:enRaw _locFbRaw:arRaw __typename}depositInfoText{locale:en _locFb:ar __typename}legalInformation{localeRaw:enRaw _locFbRaw:arRaw __typename}quickConfigs{...QuickConfigFragment __typename}channelExclusions{delivery pickup web mobile __typename}uiPattern isOfferBenefit __typename}fragment MenuImageFragment on Image{hotspot{x y height width __typename}crop{top bottom left right __typename}asset{metadata{lqip __typename}_id url __typename}__typename}fragment ComboFragment on Combo{_id _type name{locale:en _locFb:ar __typename}description{localeRaw:enRaw _locFbRaw:arRaw __typename}depositInfoText{locale:en _locFb:ar __typename}image{...MenuImageFragment __typename}imageDescription{locale:en _locFb:ar __typename}imagesByChannels{...ImagesByChannelsFragment __typename}mainItem{...ItemFragment __typename}markerItem{vendorConfigs{...VendorConfigsFragment __typename}pluConfigs{...PluConfigsFragment __typename}__typename}uiPattern hideMainItemDescription forceModifiersToBottom options{name{locale:en _locFb:ar __typename}_type _id uiPattern minAmount maxAmount respectMaximum optionVisibilitySettings{visibleOptions toggleButtonTextClosed{locale:en _locFb:ar __typename}toggleButtonTextOpen{locale:en _locFb:ar __typename}__typename}options{_key minAmount defaultAmount isPremium option{...on Item{...ItemFragment __typename}...on Picker{_type uiPattern pickerAspects{name{locale:en _locFb:ar __typename}pickerAspectOptions{name{locale:en _locFb:ar __typename}identifier __typename}__typename}__typename}__typename}__typename}__typename}menuObjectSettings{limitPerOrder __typename}isOfferBenefit __typename}fragment ItemFragment on Item{_id _type name{locale:en _locFb:ar __typename}description{localeRaw:enRaw _locFbRaw:arRaw __typename}legalInformation{localeRaw:enRaw _locFbRaw:arRaw __typename}image{...MenuImageFragment __typename}imageDescription{locale:en _locFb:ar __typename}imagesByChannels{...ImagesByChannelsFragment __typename}rewardEligible isDummyItem labelAsPerPerson nutrition{...NutritionFragment __typename}additionalItemInformation{...AdditionalItemInformationFragment __typename}nutritionWithModifiers{...NutritionFragment __typename}productSize allergens{...AllergensFragment __typename}options{...ItemOptionFragment __typename}productHierarchy{L1 L2 L3 L4 L5 __typename}menuObjectSettings{limitPerOrder __typename}channelExclusions{delivery pickup web mobile __typename}__typename}fragment NutritionFragment on Nutrition{calories caloriesPer100 carbohydrates carbohydratesPer100 cholesterol energyKJ energyKJPer100 fat fatPer100 fiber fiberPer100 proteins proteinsPer100 salt saltPer100 saturatedFat saturatedFatPer100 sodium sugar sugarPer100 transFat transFatPer100 weight __typename}fragment AdditionalItemInformationFragment on AdditionalItemInformation{ingredients{locale:en _locFb:ar __typename}additives{locale:en _locFb:ar __typename}producerDetails{locale:en _locFb:ar __typename}sourcesOfGluten additionalInformationBlock1{localeRaw:enRaw _locFbRaw:arRaw __typename}additionalInformationBlock2{localeRaw:enRaw _locFbRaw:arRaw __typename}__typename}fragment AllergensFragment on OpAllergen{milk eggs fish peanuts shellfish treeNuts soy wheat mustard sesame celery lupin gluten sulphurDioxide __typename}fragment ItemOptionFragment on ItemOption{name{locale:en _locFb:ar __typename}displayGroup{name{locale:en _locFb:ar __typename}__typename}componentStyle upsellModifier allowMultipleSelections displayModifierMultiplierName injectDefaultSelection singleChoiceOnly minAmount maxAmount _key type:_type options{_key type:_type name{locale:en _locFb:ar __typename}vendorConfigs{...VendorConfigsFragment __typename}pluConfigs{...PluConfigsFragment __typename}default modifierMultiplier{_id vendorConfigs{...VendorConfigsFragment __typename}multiplier prefix{locale:en _locFb:ar __typename}modifier{name{locale:en _locFb:ar __typename}image{...MenuImageFragment __typename}imageDescription{locale:en _locFb:ar __typename}additionalInformationBlock{localeRaw:enRaw _locFbRaw:arRaw __typename}__typename}nutrition{...NutritionFragment __typename}allergen{...AllergensFragment __typename}__typename}nutrition{...NutritionFragment __typename}allergen{...AllergensFragment __typename}__typename}__typename}fragment QuickConfigFragment on QuickConfig{name{locale:en _locFb:ar __typename}rules{itemOptions{value __typename}modifier{value __typename}__typename}__typename}";
const FEATURE_MENU_QUERY = "query featureMenu($featureMenuId:ID!){FeatureMenu(id:$featureMenuId){_id additionalDetails{additionalDetailsList{key regex required validationError{locale:en _locFb:ar __typename}isPii description{locale:en _locFb:ar __typename}__typename}__typename}menuHeroImage{locale:en{...ImageFragment __typename}__typename}menuHeroText{locale:en _locFb:ar __typename}dayParts{key endTime startTime weekDays{monday tuesday wednesday thursday friday saturday sunday __typename}displayName{locale:en _locFb:ar __typename}icon{...ImageFragment __typename}__typename}defaultMenu{_id __typename}donationTermAndConditionUrl{locale:en _locFb:ar __typename}donationItemsAtCheckout{...on Item{...ItemFragment description{localeRaw:enRaw _locFbRaw:arRaw __typename}vendorConfigs{...VendorConfigsFragment __typename}pluConfigs{...PluConfigsFragment __typename}__typename}__typename}upsellItemsAtCheckoutRestaurant{...on Item{...ItemFragment description{localeRaw:enRaw _locFbRaw:arRaw __typename}vendorConfigs{...VendorConfigsFragment __typename}pluConfigs{...PluConfigsFragment __typename}__typename}__typename}upsellItemsAtCheckoutDelivery{...on Item{...ItemFragment description{localeRaw:enRaw _locFbRaw:arRaw __typename}vendorConfigs{...VendorConfigsFragment __typename}pluConfigs{...PluConfigsFragment __typename}__typename}__typename}cartAddOnSections{...AddOnSectionFragment __typename}enableDynamicPickerImages __typename}}fragment ImageFragment on Image{hotspot{x y height width __typename}crop{top bottom left right __typename}asset{metadata{lqip __typename}_id url __typename}__typename}fragment ItemFragment on Item{_id _type name{locale:en _locFb:ar __typename}description{localeRaw:enRaw _locFbRaw:arRaw __typename}legalInformation{localeRaw:enRaw _locFbRaw:arRaw __typename}image{...MenuImageFragment __typename}imageDescription{locale:en _locFb:ar __typename}imagesByChannels{...ImagesByChannelsFragment __typename}rewardEligible isDummyItem labelAsPerPerson nutrition{...NutritionFragment __typename}additionalItemInformation{...AdditionalItemInformationFragment __typename}nutritionWithModifiers{...NutritionFragment __typename}productSize allergens{...AllergensFragment __typename}options{...ItemOptionFragment __typename}productHierarchy{L1 L2 L3 L4 L5 __typename}menuObjectSettings{limitPerOrder __typename}channelExclusions{delivery pickup web mobile __typename}__typename}fragment MenuImageFragment on Image{hotspot{x y height width __typename}crop{top bottom left right __typename}asset{metadata{lqip __typename}_id url __typename}__typename}fragment ImagesByChannelsFragment on ImagesByChannels{imageRestaurant{asset{_id metadata{lqip __typename}__typename}__typename}imageDelivery{asset{_id metadata{lqip __typename}__typename}__typename}__typename}fragment NutritionFragment on Nutrition{calories caloriesPer100 carbohydrates carbohydratesPer100 cholesterol energyKJ energyKJPer100 fat fatPer100 fiber fiberPer100 proteins proteinsPer100 salt saltPer100 saturatedFat saturatedFatPer100 sodium sugar sugarPer100 transFat transFatPer100 weight __typename}fragment AdditionalItemInformationFragment on AdditionalItemInformation{ingredients{locale:en _locFb:ar __typename}additives{locale:en _locFb:ar __typename}producerDetails{locale:en _locFb:ar __typename}sourcesOfGluten additionalInformationBlock1{localeRaw:enRaw _locFbRaw:arRaw __typename}additionalInformationBlock2{localeRaw:enRaw _locFbRaw:arRaw __typename}__typename}fragment AllergensFragment on OpAllergen{milk eggs fish peanuts shellfish treeNuts soy wheat mustard sesame celery lupin gluten sulphurDioxide __typename}fragment ItemOptionFragment on ItemOption{name{locale:en _locFb:ar __typename}displayGroup{name{locale:en _locFb:ar __typename}__typename}componentStyle upsellModifier allowMultipleSelections displayModifierMultiplierName injectDefaultSelection singleChoiceOnly minAmount maxAmount _key type:_type options{_key type:_type name{locale:en _locFb:ar __typename}vendorConfigs{...VendorConfigsFragment __typename}pluConfigs{...PluConfigsFragment __typename}default modifierMultiplier{_id vendorConfigs{...VendorConfigsFragment __typename}multiplier prefix{locale:en _locFb:ar __typename}modifier{name{locale:en _locFb:ar __typename}image{...MenuImageFragment __typename}imageDescription{locale:en _locFb:ar __typename}additionalInformationBlock{localeRaw:enRaw _locFbRaw:arRaw __typename}__typename}nutrition{...NutritionFragment __typename}allergen{...AllergensFragment __typename}__typename}nutrition{...NutritionFragment __typename}allergen{...AllergensFragment __typename}__typename}__typename}fragment VendorConfigsFragment on VendorConfigs{ncr{...VendorConfigFragment __typename}ncrDelivery{...VendorConfigFragment __typename}partner{...VendorConfigFragment __typename}partnerDelivery{...VendorConfigFragment __typename}productNumber{...VendorConfigFragment __typename}productNumberDelivery{...VendorConfigFragment __typename}sicom{...VendorConfigFragment __typename}sicomDelivery{...VendorConfigFragment __typename}qdi{...VendorConfigFragment __typename}qdiDelivery{...VendorConfigFragment __typename}rpos{...VendorConfigFragment __typename}rposDelivery{...VendorConfigFragment __typename}simplyDelivery{...VendorConfigFragment __typename}simplyDeliveryDelivery{...VendorConfigFragment __typename}toshibaLoyalty{...VendorConfigFragment __typename}__typename}fragment VendorConfigFragment on VendorConfig{pluType parentSanityId pullUpLevels constantPlu discountPlu quantityBasedPlu{quantity plu qualifier __typename}multiConstantPlus{quantity plu qualifier __typename}parentChildPlu{plu childPlu __typename}sizeBasedPlu{comboPlu comboSize __typename}__typename}fragment PluConfigsFragment on PluConfigs{_key _type partner{...PluConfigFragment __typename}__typename}fragment PluConfigFragment on PluConfig{_key _type posIntegration{_id _type name __typename}serviceMode vendorConfig{...VendorConfigFragment __typename}__typename}fragment AddOnSectionFragment on AddOnSection{_id _key name{locale:en _locFb:ar __typename}maxAmount options{...AddOnSectionOptionFragment __typename}showSectionItemsOnCart sectionItemsServiceModes{...AddOnSectionServiceModesFragment __typename}enableAddonAsFreeItem __typename}fragment AddOnSectionOptionFragment on AddOnSectionOption{_key maxAmount option{...ItemFragment ...ItemAvailabilityFragment __typename}freeOption{...ItemFragment ...ItemAvailabilityFragment __typename}itemsAcceptingFreeOffers{...AddOnSectionItemAccepetingFreeFragment __typename}addOnSectionFreeModalInfos{...AddOnSectionFreeModalInfosFragment __typename}__typename}fragment ItemAvailabilityFragment on Item{operationalItem{daypart __typename}vendorConfigs{...VendorConfigsFragment __typename}pluConfigs{...PluConfigsFragment __typename}showInStaticMenu hideCalories hideNutritionLegalDisclaimer itemSize itemUnit options{...ItemOptionAvailabilityFragment __typename}__typename}fragment ItemOptionAvailabilityFragment on ItemOption{injectDefaultSelection options{default vendorConfigs{...VendorConfigsFragment __typename}pluConfigs{...PluConfigsFragment __typename}modifierMultiplier{_id vendorConfigs{...VendorConfigsFragment __typename}pluConfigs{...PluConfigsFragment __typename}modifier{vendorConfigs{...VendorConfigsFragment __typename}pluConfigs{...PluConfigsFragment __typename}__typename}__typename}__typename}__typename}fragment AddOnSectionItemAccepetingFreeFragment on AddOnSectionItemAcceptingFreeOffer{_key maxFreeQuantity itemAcceptingFreeOffer{...on Item{_id name{locale:en _locFb:ar __typename}__typename}...on Combo{_id name{locale:en _locFb:ar __typename}__typename}__typename}__typename}fragment AddOnSectionFreeModalInfosFragment on AddOnSectionFreeModalFieldset{showFreeAddOnModal image{locale:en{...ImagesFragment __typename}__typename}title{locale:en _locFb:ar __typename}description{locale:en _locFb:ar __typename}primaryButtonText{locale:en _locFb:ar __typename}__typename}fragment ImagesFragment on Images{app{...ImageFragment __typename}imageDescription __typename}fragment AddOnSectionServiceModesFragment on AddOnSectionServiceModes{pickUpServiceMode driveThruServiceMode curbsideServiceMode dineInServiceMode tableServiceMode deliveryServiceMode __typename}";

function newSessionId() {
  // RFC4122-ish v4 UUID, good enough as a throwaway anonymous session
  // identifier - not tied to any real account, never persisted to disk.
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

function buildHeaders(extra = {}) {
  return {
    ...CONFIG.STATIC_API_HEADERS,
    'x-user-datetime': new Date().toISOString(),
    'x-session-id': newSessionId(),
    ...extra,
  };
}

function getPath(obj, dotPath) {
  return dotPath.split('.').reduce((acc, key) => (acc && typeof acc === 'object' ? acc[key] : undefined), obj);
}

function has(obj, dotPath, mustBeArray) {
  const val = getPath(obj, dotPath);
  if (val === undefined || val === null) return false;
  if (mustBeArray) return Array.isArray(val);
  return true;
}

/** Validates a parsed response body against required (and optionally array) dot-paths. */
function schemaCheck(data, requiredPaths, arrayPaths = []) {
  for (const p of requiredPaths) {
    if (!has(data, p, arrayPaths.includes(p))) {
      return { valid: false, reason: `missing or wrong-shaped field: ${p}` };
    }
  }
  return { valid: true, reason: null };
}

/**
 * Performs one GraphQL call. Burger King's endpoints accept a single
 * {operationName, variables, query} JSON object body (not an array/batch
 * - confirmed live: an array body 400s with a "must provide a query"
 * error on the Sanity endpoint, while a plain object works on every
 * endpoint, so a plain object is used everywhere for consistency).
 */
async function call({ url, operationName, variables, query, logger, label }) {
  try {
    const res = await http.request({
      method: 'POST',
      url,
      headers: buildHeaders(),
      body: { operationName, variables, query },
      timeoutMs: CONFIG.API_TIMEOUT,
    });
    if (res.parseError) {
      return { ok: false, status: res.status, data: null, raw: res.body, error: `JSON parse error: ${res.parseError}` };
    }
    const payload = res.json;
    const gqlErrors = payload && payload.errors;
    if (gqlErrors && gqlErrors.length) {
      if (logger) logger.tag('API', `${label || operationName} returned GraphQL errors: ${gqlErrors.map((e) => e.message).join('; ')}`);
    }
    return { ok: res.status >= 200 && res.status < 300, status: res.status, data: payload ? payload.data : null, raw: payload, error: null };
  } catch (e) {
    if (logger) logger.tag('API', `${label || operationName} request failed: ${e.message}`);
    return { ok: false, status: null, data: null, raw: null, error: e.message };
  }
}

/** Find candidate restaurants near a coordinate. filter: 'NEARBY' | 'DELIVERY_DELIVERS_TO'. */
async function getRestaurants({ lat, lng, searchRadius = 8000, filter = 'NEARBY', first = 1000 }, logger) {
  const result = await call({
    url: CONFIG.GRAPHQL.RBI_GATEWAY,
    operationName: 'GetRestaurants',
    variables: { input: { filter, coordinates: { userLat: lat, userLng: lng, searchRadius }, first, status: 'OPEN', parallelFlag: false } },
    query: GET_RESTAURANTS_QUERY,
    logger,
    label: 'getRestaurants',
  });
  const schema = schemaCheck(result.data, ['restaurants.nodes'], ['restaurants.nodes']);
  return { ...result, schema };
}

/** Single-restaurant lookup by storeId - hours + availability. */
async function getRestaurant({ storeId }, logger) {
  const result = await call({
    url: CONFIG.GRAPHQL.RBI_GATEWAY,
    operationName: 'GetRestaurant',
    variables: { storeId: String(storeId) },
    query: GET_RESTAURANT_QUERY,
    logger,
    label: 'getRestaurant',
  });
  const schema = schemaCheck(result.data, ['restaurant']);
  return { ...result, schema };
}

/**
 * Delivery-availability + quote check for a dropoff address (Burger
 * King's equivalent of KFC's validateLocation). phoneNumber is always
 * sent empty - never fill a real phone number here.
 */
async function deliveryRestaurant({ addressLine1, addressLine2 = '', city, route, state = '', streetNumber, zip = '', latitude, longitude, searchRadius = 8000 }, logger) {
  const result = await call({
    url: CONFIG.GRAPHQL.RBI_GATEWAY,
    operationName: 'DeliveryRestaurant',
    variables: {
      dropoff: { addressLine1, addressLine2, city, route, state, streetNumber, zip, country: 'SAU', latitude, longitude, phoneNumber: '' },
      searchRadius,
      platform: 'web',
    },
    query: DELIVERY_RESTAURANT_QUERY,
    logger,
    label: 'deliveryRestaurant',
  });
  const schema = schemaCheck(result.data, ['deliveryRestaurant.storeStatus']);
  return { ...result, schema };
}

/** Resolves the current published Menu document id (see api-map.md "GetMenuSections"). */
async function featureMenu(logger) {
  const result = await call({
    url: CONFIG.GRAPHQL.SANITY,
    operationName: 'featureMenu',
    variables: { featureMenuId: 'feature-menu-singleton' },
    query: FEATURE_MENU_QUERY,
    logger,
    label: 'featureMenu',
  });
  const schema = schemaCheck(result.data, ['FeatureMenu.defaultMenu._id']);
  return { ...result, schema };
}

/** Full menu structure (categories -> combos/items) - not store/channel-scoped, see api-map.md. */
async function getMenuSections({ menuId }, logger) {
  const result = await call({
    url: `${CONFIG.GRAPHQL.SANITY}?operationName=GetMenuSections`,
    operationName: 'GetMenuSections',
    variables: { id: menuId },
    query: GET_MENU_SECTIONS_QUERY,
    logger,
    label: 'getMenuSections',
  });
  const schema = schemaCheck(result.data, ['Menu.options'], ['Menu.options']);
  return { ...result, schema };
}

// Store-scoped pricing (RBI gateway). Confirmed live: POST with content-type
// application/json works; Apollo @gateway/@useCache directives must NOT be
// sent on standalone POSTs (validation 400). Prices are integer cents.
const STORE_MENU_QUERY = 'query storeMenu($region:String!$channel:Channel!$storeId:ID!$serviceMode:PosDataServiceMode){storeMenu(region:$region channel:$channel storeId:$storeId serviceMode:$serviceMode){id isAvailable price{default max min overrides{key price}}}}';
const PLUS_DATA_QUERY = 'query plusData($storeId:ID!$serviceMode:PosDataServiceMode){plus(storeId:$storeId serviceMode:$serviceMode){plu price}}';

/**
 * Per-store entity prices keyed by Sanity/POS id (same _id as GetMenuSections
 * products and picker option children). serviceMode: 'pickup' | 'delivery'.
 */
async function storeMenu({ storeId, serviceMode = 'pickup', channel = 'whitelabel', region = 'SA' }, logger) {
  const result = await call({
    url: CONFIG.GRAPHQL.RBI_GATEWAY,
    operationName: 'storeMenu',
    variables: {
      region,
      channel,
      storeId: String(storeId),
      serviceMode,
    },
    query: STORE_MENU_QUERY,
    logger,
    label: 'storeMenu',
  });
  const schema = schemaCheck(result.data, ['storeMenu'], ['storeMenu']);
  return { ...result, schema };
}

/**
 * PLU → price (cents as string) for the store/serviceMode. Useful when a
 * storeMenu entity's default/min are 0 but a vendorConfigs.constantPlu is set.
 */
async function plusData({ storeId, serviceMode = 'pickup' }, logger) {
  const result = await call({
    url: CONFIG.GRAPHQL.RBI_GATEWAY,
    operationName: 'plusData',
    variables: {
      storeId: String(storeId),
      serviceMode,
    },
    query: PLUS_DATA_QUERY,
    logger,
    label: 'plusData',
  });
  const schema = schemaCheck(result.data, ['plus'], ['plus']);
  return { ...result, schema };
}

module.exports = {
  buildHeaders,
  newSessionId,
  call,
  schemaCheck,
  getPath,
  getRestaurants,
  getRestaurant,
  deliveryRestaurant,
  featureMenu,
  getMenuSections,
  storeMenu,
  plusData,
};
